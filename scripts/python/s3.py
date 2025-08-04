#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "boto3",
# ]
# ///

import ipaddress
import logging
import os
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

AWS_ENDPOINT = os.getenv("AWS_ENDPOINT", None)
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY", None)
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY", None)
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", None)


if (
    AWS_ENDPOINT is None
    or AWS_ACCESS_KEY is None
    or AWS_SECRET_KEY is None
    or AWS_S3_BUCKET is None
):
    raise ValueError(
        "AWS configuration is incomplete. Please set AWS_ENDPOINT, "
        "AWS_ACCESS_KEY, AWS_SECRET_KEY, and AWS_S3_BUCKET environment variables."
    )


class S3FileWrapper:
    """
    A comprehensive S3 file wrapper class for uploading and downloading files.

    This class provides a clean interface for S3 operations including:
    - File upload and download
    - Bucket management
    - File listing and filtering
    - Presigned URL generation
    - Error handling
    """

    def __init__(self):
        """
        Initialize the S3 wrapper with configuration from settings.

        All configuration is taken from the application settings:
        - endpoint_url: S3 endpoint URL (from settings.AWS_ENDPOINT)
        - access_key_id: AWS access key ID (from settings.AWS_ACCESS_KEY)
        - secret_access_key: AWS secret access key (from settings.AWS_SECRET_KEY)
        - bucket_name: S3 bucket name (from settings.AWS_S3_BUCKET)
        - verify_ssl: Automatically determined based on endpoint URL
        """
        self.region_name = None
        self.verify_ssl = self._should_verify_ssl()

        # Initialize S3 client
        self._client = self._create_client()

        if self.verify_connection() is False:
            raise ConnectionError(
                f"Could not connect to S3 bucket '{AWS_S3_BUCKET}'. Please check your credentials and configuration."
            )

    def _should_verify_ssl(self) -> bool:
        """
        Determine whether SSL verification should be enabled based on the endpoint URL.

        Returns False if:
        - Endpoint URL uses HTTP (not HTTPS)
        - AND the host is an IP address

        Returns True otherwise.

        Returns:
            bool: True if SSL should be verified, False otherwise.
        """
        try:
            parsed_url = urlparse(AWS_ENDPOINT)

            # If scheme is not https, check if host is an IP address
            if parsed_url.scheme.lower() != "https":
                try:
                    # Try to parse the hostname as an IP address
                    ipaddress.ip_address(parsed_url.hostname)
                    # If it's an IP address and not HTTPS, disable SSL verification
                    logger.info(
                        f"Endpoint '{AWS_ENDPOINT}' is HTTP with IP address, disabling SSL verification"
                    )
                    return False
                except (ValueError, TypeError):
                    # Not an IP address, keep SSL verification enabled
                    pass

            # Default to SSL verification enabled
            return True

        except Exception as e:
            logger.warning(
                f"Could not parse endpoint URL '{AWS_ENDPOINT}': {e}. Defaulting to SSL verification enabled."
            )
            return True

    def _create_client(self) -> boto3.client:
        """Create and configure the S3 client."""
        config = Config(
            signature_version="s3v4", retries={"max_attempts": 3, "mode": "adaptive"}
        )

        client_params = {
            "service_name": "s3",
            "endpoint_url": AWS_ENDPOINT,
            "aws_access_key_id": AWS_ACCESS_KEY,
            "aws_secret_access_key": AWS_SECRET_KEY,
            "config": config,
            "verify": self.verify_ssl,
        }

        if self.region_name:
            client_params["region_name"] = self.region_name

        return boto3.client(**client_params)

    def verify_connection(self) -> bool:
        """
        Verify S3 connection and bucket access.

        Returns:
            True if connection and bucket access is successful, False otherwise.
        """
        try:
            self._client.head_bucket(Bucket=AWS_S3_BUCKET)
            logger.info(f"Successfully verified connection to bucket '{AWS_S3_BUCKET}'")
            return True
        except ClientError as e:
            logger.error(f"Failed to verify bucket access: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during connection verification: {e}")
            return False

    def upload_file(
        self,
        local_file_path: str | Path,
        s3_key: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
        storage_class: str = "STANDARD",
    ) -> bool:
        """
        Upload a file to S3.

        Args:
            local_file_path: Path to the local file to upload
            s3_key: S3 object key (defaults to filename)
            metadata: Additional metadata to store with the file
            content_type: MIME content type of the file
            storage_class: S3 storage class (STANDARD, REDUCED_REDUNDANCY, etc.)

        Returns:
            True if upload successful, False otherwise.
        """
        local_path = Path(local_file_path)

        if not local_path.exists():
            logger.error(f"Local file not found: {local_path}")
            return False

        if not local_path.is_file():
            logger.error(f"Path is not a file: {local_path}")
            return False

        # Use filename as S3 key if not provided
        object_key = s3_key or local_path.name

        try:
            extra_args = {"StorageClass": storage_class}

            if metadata:
                extra_args["Metadata"] = metadata

            if content_type:
                extra_args["ContentType"] = content_type

            logger.info(f"Uploading {local_path} to s3://{AWS_S3_BUCKET}/{object_key}")

            self._client.upload_file(
                str(local_path), AWS_S3_BUCKET, object_key, ExtraArgs=extra_args
            )

            logger.info(
                f"Successfully uploaded file to s3://{AWS_S3_BUCKET}/{object_key}"
            )
            return True

        except ClientError as e:
            logger.error(f"Failed to upload file: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}")
            return False

    def download_file(
        self,
        s3_key: str,
        local_file_path: Optional[str | Path] = None,
        create_dirs: bool = True,
    ) -> Optional[Path]:
        """
        Download a file from S3.

        Args:
            s3_key: S3 object key to download
            local_file_path: Local path to save the file (defaults to filename in current dir)
            create_dirs: Whether to create parent directories if they don't exist

        Returns:
            Path to the downloaded file if successful, None otherwise.
        """
        if local_file_path is None:
            local_file_path = Path(s3_key).name

        local_path = Path(local_file_path)

        # Create parent directories if needed
        if create_dirs and local_path.parent != Path():
            local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            logger.info(f"Downloading s3://{AWS_S3_BUCKET}/{s3_key} to {local_path}")

            self._client.download_file(AWS_S3_BUCKET, s3_key, str(local_path))

            logger.info(f"Successfully downloaded file to {local_path}")
            return local_path

        except ClientError as e:
            logger.error(f"Failed to download file: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during download: {e}")
            return None

    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        s3_key: str,
        metadata: Optional[Dict[str, str]] = None,
        content_type: Optional[str] = None,
    ) -> bool:
        """
        Upload a file-like object to S3.

        Args:
            file_obj: File-like object to upload
            s3_key: S3 object key
            metadata: Additional metadata to store with the file
            content_type: MIME content type of the file

        Returns:
            True if upload successful, False otherwise.
        """
        try:
            extra_args = {}

            if metadata:
                extra_args["Metadata"] = metadata

            if content_type:
                extra_args["ContentType"] = content_type

            logger.info(f"Uploading file object to s3://{AWS_S3_BUCKET}/{s3_key}")

            self._client.upload_fileobj(
                file_obj, AWS_S3_BUCKET, s3_key, ExtraArgs=extra_args
            )

            logger.info(
                f"Successfully uploaded file object to s3://{AWS_S3_BUCKET}/{s3_key}"
            )
            return True

        except ClientError as e:
            logger.error(f"Failed to upload file object: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}")
            return False

    def list_files(
        self,
        prefix: str = "",
        max_keys: int = 1000,
        extensions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        List files in the S3 bucket.

        Args:
            prefix: Only list files with this prefix
            max_keys: Maximum number of files to return
            extensions: Only return files with these extensions (e.g., ['.jpg', '.png'])

        Returns:
            List of file information dictionaries.
        """
        try:
            response = self._client.list_objects_v2(
                Bucket=AWS_S3_BUCKET, Prefix=prefix, MaxKeys=max_keys
            )

            files = []
            if "Contents" in response:
                for obj in response["Contents"]:
                    key = obj["Key"]

                    # Filter by extensions if provided
                    if extensions and not any(
                        key.lower().endswith(ext.lower()) for ext in extensions
                    ):
                        continue

                    files.append(
                        {
                            "key": key,
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"],
                            "etag": obj["ETag"].strip('"'),
                        }
                    )

            logger.info(
                f"Found {len(files)} files in bucket '{AWS_S3_BUCKET}' with prefix '{prefix}'"
            )
            return files

        except ClientError as e:
            logger.error(f"Failed to list files: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during file listing: {e}")
            return []

    def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3.

        Args:
            s3_key: S3 object key to check

        Returns:
            True if file exists, False otherwise.
        """
        try:
            self._client.head_object(Bucket=AWS_S3_BUCKET, Key=s3_key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            logger.error(f"Error checking file existence: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking file existence: {e}")
            return False

    def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3.

        Args:
            s3_key: S3 object key to delete

        Returns:
            True if deletion successful, False otherwise.
        """
        try:
            self._client.delete_object(Bucket=AWS_S3_BUCKET, Key=s3_key)
            logger.info(f"Successfully deleted s3://{AWS_S3_BUCKET}/{s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete file: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during deletion: {e}")
            return False

    def generate_presigned_url(
        self,
        s3_key: str,
        expiration: int = 3600,
        method: str = "get_object",
    ) -> Optional[str]:
        """
        Generate a presigned URL for S3 object access.

        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)
            method: HTTP method ('get_object' for download, 'put_object' for upload)

        Returns:
            Presigned URL if successful, None otherwise.
        """
        try:
            url = self._client.generate_presigned_url(
                method,
                Params={"Bucket": AWS_S3_BUCKET, "Key": s3_key},
                ExpiresIn=expiration,
            )
            logger.info(f"Generated presigned URL for s3://{AWS_S3_BUCKET}/{s3_key}")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {e}")
            return None

    def get_file_info(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata and information about an S3 object.

        Args:
            s3_key: S3 object key

        Returns:
            Dictionary with file information if successful, None otherwise.
        """
        try:
            response = self._client.head_object(Bucket=AWS_S3_BUCKET, Key=s3_key)

            return {
                "key": s3_key,
                "size": response.get("ContentLength"),
                "last_modified": response.get("LastModified"),
                "content_type": response.get("ContentType"),
                "etag": response.get("ETag", "").strip('"'),
                "metadata": response.get("Metadata", {}),
                "storage_class": response.get("StorageClass"),
            }
        except ClientError as e:
            logger.error(f"Failed to get file info: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting file info: {e}")
            return None


def main():
    """Example usage and testing of the S3FileWrapper class."""
    # Initialize S3 wrapper
    s3_wrapper = S3FileWrapper()

    logger.info(f"Successfully connected to S3 bucket '{AWS_S3_BUCKET}'")

    # List JPG files
    logger.info("Listing JPG files in bucket:")
    jpg_files = s3_wrapper.list_files(extensions=[".jpg", ".jpeg"])

    if not jpg_files:
        logger.info("No JPG files found in the bucket.")
        return

    for file_info in jpg_files:
        logger.info(f"  - {file_info['key']} ({file_info['size']} bytes)")

    # Download the first jpg file found
    if jpg_files:
        file_to_download = jpg_files[0]["key"]
        local_file_path = Path(file_to_download).name

        logger.info(f"Downloading '{file_to_download}' to '{local_file_path}'...")
        downloaded_path = s3_wrapper.download_file(file_to_download, local_file_path)

        if downloaded_path:
            logger.info(f"Successfully downloaded file to {downloaded_path}")
        else:
            logger.error("Failed to download file")


if __name__ == "__main__":
    main()
