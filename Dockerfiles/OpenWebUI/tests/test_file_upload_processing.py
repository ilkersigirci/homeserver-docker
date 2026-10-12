"""ENABLE_FILE_UPLOAD_PROCESSING=false keeps chat uploads raw."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.routers import files


async def processed(setting: str | None, requested: bool) -> bool:
    """Whether an upload that asked for processing reaches the handler with it."""
    handler = AsyncMock(return_value=SimpleNamespace(id="file-id", filename="report.pdf", meta={}))
    with (
        patch.dict(os.environ, {}),
        patch.object(files, "upload_file_handler", handler),
        patch.object(files, "publish_event", AsyncMock()),
    ):
        os.environ.pop("ENABLE_FILE_UPLOAD_PROCESSING", None)
        if setting is not None:
            os.environ["ENABLE_FILE_UPLOAD_PROCESSING"] = setting
        await files.upload_file(
            request=SimpleNamespace(),
            background_tasks=SimpleNamespace(),
            file=SimpleNamespace(),
            metadata=None,
            process=requested,
            process_in_background=True,
            user=SimpleNamespace(id="user-id"),
            db=None,
        )
    return handler.await_args.kwargs["process"]


class FileUploadProcessingTest(unittest.IsolatedAsyncioTestCase):
    async def test_uploads_are_processed_as_requested_by_default(self) -> None:
        for setting in (None, "true"):
            with self.subTest(setting=setting):
                self.assertTrue(await processed(setting, requested=True))
                self.assertFalse(await processed(setting, requested=False))

    async def test_disabled_processing_keeps_every_upload_raw(self) -> None:
        self.assertFalse(await processed("false", requested=True))


if __name__ == "__main__":
    unittest.main()
