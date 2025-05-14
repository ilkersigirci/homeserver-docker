#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "boto3",
# ]
# ///

import os
import sys

import boto3
from botocore.exceptions import ClientError


def main():
    minio_endpoint = "https://minio.gpu.ilkerflix.com"
    minio_access_key = "admin"
    minio_secret_key = "password"
    bucket_name = "ilkerflix-bucket"

    try:
        # Initialize S3 client using boto3
        print(f"Connecting to MinIO at {minio_endpoint}...")
        s3_client = boto3.client(
            "s3",
            endpoint_url=minio_endpoint,
            aws_access_key_id=minio_access_key,
            aws_secret_access_key=minio_secret_key,
            # The following parameters might be needed for some setups
            config=boto3.session.Config(signature_version="s3v4"),
            verify=True,
        )

        # Check if the bucket exists
        try:
            s3_client.head_bucket(Bucket=bucket_name)
            print(
                f"Successfully connected to MinIO and verified bucket '{bucket_name}' exists."
            )
        except ClientError as e:
            print(
                f"Error: Bucket '{bucket_name}' does not exist or you don't have access."
            )
            sys.exit(1)

        # List all objects in the bucket with .jpg or .jpeg extension
        print(f"Listing JPG files in bucket '{bucket_name}':")
        response = s3_client.list_objects_v2(Bucket=bucket_name)

        jpg_files = []
        if "Contents" in response:
            for obj in response["Contents"]:
                key = obj["Key"]
                if key.lower().endswith((".jpg", ".jpeg")):
                    jpg_files.append(key)
                    print(f"  - {key} ({obj['Size']} bytes)")

        if not jpg_files:
            print("No JPG files found in the bucket.")
            sys.exit(0)

        # Download the first jpg file found
        if jpg_files:
            file_to_download = jpg_files[0]
            local_file_path = os.path.basename(file_to_download)

            print(f"Downloading '{file_to_download}' to '{local_file_path}'...")
            s3_client.download_file(bucket_name, file_to_download, local_file_path)
            print(f"Successfully downloaded file to {local_file_path}")

    except ClientError as e:
        print(f"AWS S3 Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
