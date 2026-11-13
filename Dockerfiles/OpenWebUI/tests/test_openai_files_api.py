"""Chat documents and images go through an OpenAI-compatible Files API: sent by file ID or extracted there."""

import contextlib
import copy
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from open_webui.retrieval.loaders.main import Loader
from open_webui.routers import openai, retrieval
from open_webui.utils import middleware, openai_files
from open_webui.utils import tools as builtin_tools
from starlette.requests import Request

GATEWAY = "https://gateway.example/v1"
USER = SimpleNamespace(id="user-id", role="user", name="User", email="user@example.com")
TOKEN = {"access_token": "user-token"}
MARKDOWN = "# Rapor\n\nÇıkarılan metin."
# The builtin tools offered for a chat's own files; display_file also serves knowledge bases.
CHAT_FILE_TOOLS = {"list_chat_files", "query_chat_files", "grep_chat_files", "view_file"}


class FakeFilesApi:
    """files-api behind httpx.MockTransport: numbers each upload, answers status checks
    with `statuses` in turn (the last one repeating), and serves `content`."""

    def __init__(
        self,
        upload_status: int = 200,
        statuses: tuple[dict, ...] = ({"status": "processed"},),
        content: httpx.Response | None = None,
    ) -> None:
        self.upload_status = upload_status
        self.statuses = statuses
        self.content = content or httpx.Response(200, json={"results": [{"md_content": MARKDOWN}]})
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            if self.upload_status != 200:
                return httpx.Response(self.upload_status, json={"error": {"message": "Unauthorized"}})
            return httpx.Response(200, json=file_object(f"file-{len(self.uploads)}", status="uploaded"))
        if request.url.path.endswith("/content"):
            return self.content
        fields = self.statuses[min(len(self.status_checks), len(self.statuses)) - 1]
        return httpx.Response(200, json=file_object(request.url.path.rsplit("/", 1)[-1], **fields))

    @property
    def uploads(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]

    @property
    def status_checks(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "GET" and not r.url.path.endswith("/content")]


def file_object(id: str, **fields) -> dict:
    return {"id": id, "object": "file", "bytes": 1, "created_at": 1, "filename": "f", "purpose": "user_data", **fields}


async def parse_upload(upload: httpx.Request):
    """The upload's multipart form, parsed as a FastAPI Files API parses it."""

    async def receive() -> dict:
        return {"type": "http.request", "body": upload.content, "more_body": False}

    headers = [(b"content-type", upload.headers["content-type"].encode())]
    return await Request({"type": "http", "method": "POST", "headers": headers}, receive).form()


@contextlib.contextmanager
def files_api(api: FakeFilesApi, *patches, token: object = TOKEN, pattern: str = "^langflow/"):
    """The image's Files API settings, behind a system_oauth connection to the same gateway."""
    connections = (True, [GATEWAY], [""], {"0": {"auth_type": "system_oauth"}})
    clients: list[dict] = []

    def http_client(**kwargs) -> httpx.AsyncClient:
        clients.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(api))

    with contextlib.ExitStack() as stack:
        for manager in (
            patch.multiple(
                openai_files,
                OPENAI_FILES_API_BASE_URL=GATEWAY,
                OPENAI_FILES_API_KEY="static-key",
                OPENAI_FILES_API_PARAMS={"provider": "files"},
                OPENAI_FILES_API_MODELS_REGEX=re.compile(pattern or "(?!)"),
                OPENAI_FILES_API_TIMEOUT=300,
                PROCESSING_POLL_SECONDS=0,
                DefaultAsyncHttpxClient=http_client,
            ),
            patch("open_webui.routers.openai.get_openai_runtime_config", AsyncMock(return_value=connections)),
            patch("open_webui.utils.middleware.get_system_oauth_token", AsyncMock(return_value=token)),
            patch.object(openai_files.Storage, "get_file", side_effect=lambda path: path),
            *patches,
        ):
            stack.enter_context(manager)
        yield clients


def stored_file(workdir: Path, id: str, name: str, content_type: str, **meta) -> SimpleNamespace:
    path = workdir / name
    path.write_bytes(f"{name} bytes".encode())
    return SimpleNamespace(
        id=id, user_id=USER.id, path=str(path), filename=name, meta={"content_type": content_type, **meta}, data={}
    )


class FileIdsCase(unittest.IsolatedAsyncioTestCase):
    """Sends self.messages, with self.files as the request's files, from the stored self.records."""

    async def send(self, model: dict, api: FakeFilesApi, save_id: AsyncMock, **settings) -> tuple[dict, dict]:
        # As in a real request, metadata['files'] starts as the request's own files list.
        form_data = {"messages": copy.deepcopy(self.messages), "files": copy.deepcopy(self.files)}
        metadata = {"files": form_data["files"]}
        get_files = AsyncMock(side_effect=lambda ids: [self.records[id] for id in ids])
        with files_api(
            api,
            patch.object(openai_files.Files, "get_files_by_ids", get_files),
            patch.object(openai_files.Files, "update_file_metadata_by_id", save_id),
            patch.object(openai_files, "has_access_to_file", AsyncMock(return_value=False)),
            **settings,
        ):
            await openai_files.add_file_id_parts(SimpleNamespace(), form_data, metadata, USER, model)
        return form_data, metadata


class SendFileIdsTest(FileIdsCase):
    def setUp(self) -> None:
        workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        cached = stored_file(workdir, "cached", "a.pdf", "application/pdf", openai_file_id="file-cached")
        new = stored_file(workdir, "new", 'Rapor "son" şubat 2026.docx', "application/msword")
        image = stored_file(workdir, "image", "c.png", "image/png")
        audio = stored_file(workdir, "audio", "voice.mp3", "audio/mpeg")
        foreign = stored_file(workdir, "foreign", "d.pdf", "application/pdf")
        foreign.user_id = "other-user"
        notes = stored_file(workdir, "notes", "notes.csv", "text/csv")
        self.records = {file.id: file for file in (cached, new, image, audio, foreign, notes)}

        def item(file: SimpleNamespace) -> dict:
            return {"type": "image" if file is image else "file", "id": file.id, "name": file.filename}

        self.messages = [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Summarize.", "files": [item(cached), item(image), item(new)]},
            {"role": "assistant", "content": "Done."},
            {
                "role": "user",
                "content": [{"type": "text", "text": "Compare."}],
                "files": [item(new), item(audio), item(foreign), item(notes)],
            },
        ]
        self.files = [*(item(file) for file in self.records.values()), {"type": "collection", "id": "kb"}]

    async def test_matching_models_receive_each_message_documents_by_file_id(self) -> None:
        api, save_id = FakeFilesApi(), AsyncMock()
        form_data, metadata = await self.send({"id": "langflow/flow"}, api, save_id)
        _, first, _, second = form_data["messages"]
        new_part = {"type": "file", "file": {"file_id": "file-1", "filename": 'Rapor "son" şubat 2026.docx'}}

        self.assertEqual(
            first["content"],
            [
                {"type": "text", "text": "Summarize."},
                {"type": "file", "file": {"file_id": "file-cached", "filename": "a.pdf"}},
                new_part,
            ],
        )
        self.assertEqual(second["content"], [{"type": "text", "text": "Compare."}, new_part])
        # An image no image_url part shows, audio, another user's file, and types the Files API
        # does not extract keep Open WebUI's usual handling.
        self.assertEqual([file["id"] for file in first["files"]], ["image"])
        self.assertEqual([file["id"] for file in second["files"]], ["audio", "foreign", "notes"])
        # Retrieval and the file tools no longer see the documents sent by ID, in either list.
        for files in (metadata["files"], form_data["files"]):
            self.assertEqual([file["id"] for file in files], ["image", "audio", "foreign", "notes", "kb"])

        # The file without an ID is uploaded once, though two messages attach it, and keeps its ID.
        # Models that read files by ID do not wait for text extraction.
        [upload] = api.requests
        self.assertEqual(str(upload.url.copy_with(query=None)), f"{GATEWAY}/files")
        self.assertEqual(dict(upload.url.params), {"provider": "files"})
        self.assertEqual(upload.headers["Authorization"], "Bearer user-token")
        self.assertEqual(upload.extensions["timeout"], {"connect": 5.0, "read": 300, "write": 300, "pool": 300})
        save_id.assert_awaited_once_with("new", {"openai_file_id": "file-1"})

    async def test_the_files_api_receives_the_file_and_its_name(self) -> None:
        api = FakeFilesApi()
        await self.send({"id": "langflow/flow"}, api, AsyncMock())

        form = await parse_upload(api.uploads[0])
        self.addAsyncCleanup(form.close)
        self.assertEqual(form["purpose"], "user_data")
        # httpx escapes quotes as HTML forms do; files-api and OpenAI decode them.
        self.assertEqual(form["file"].filename, "Rapor %22son%22 şubat 2026.docx")
        self.assertEqual(form["file"].content_type, "application/msword")
        self.assertEqual(await form["file"].read(), 'Rapor "son" şubat 2026.docx bytes'.encode())

    async def test_a_failed_upload_keeps_that_document_on_open_webui_handling(self) -> None:
        # Without an OAuth session, the upload carries no token, never the key, and is refused.
        api = FakeFilesApi(upload_status=401)
        form_data, metadata = await self.send({"id": "langflow/flow"}, api, AsyncMock(), token=None)
        _, first, _, second = form_data["messages"]

        self.assertNotIn("Authorization", api.uploads[0].headers)
        self.assertEqual(second["content"], [{"type": "text", "text": "Compare."}])
        self.assertEqual([file["id"] for file in second["files"]], ["new", "audio", "foreign", "notes"])
        # The document with an ID is still sent by ID.
        self.assertEqual(first["content"][-1]["file"]["file_id"], "file-cached")
        self.assertIn("new", [file["id"] for file in metadata["files"]])

    async def test_workspace_models_match_through_their_base_model(self) -> None:
        model = {"id": "my-assistant", "info": {"base_model_id": "langflow/flow"}}
        form_data, _ = await self.send(model, FakeFilesApi(), AsyncMock())

        self.assertEqual(form_data["messages"][3]["content"][-1]["file"]["file_id"], "file-1")

    async def test_other_models_and_an_empty_pattern_keep_upstream_behavior(self) -> None:
        for model_id, pattern in (("openai/gpt", "^langflow/"), ("langflow/flow", "")):
            with self.subTest(model_id=model_id, pattern=pattern):
                api = FakeFilesApi()
                form_data, metadata = await self.send({"id": model_id}, api, AsyncMock(), pattern=pattern)

                self.assertEqual(form_data["messages"], self.messages)
                self.assertEqual(metadata["files"], self.files)
                self.assertEqual(api.requests, [])

    def test_an_invalid_pattern_or_a_missing_base_url_turns_file_ids_off(self) -> None:
        for base_url, pattern in ((GATEWAY, "^langflow/("), ("", "^langflow/")):
            with self.subTest(base_url=base_url, pattern=pattern):
                # A fresh copy of the module reads the settings, as Open WebUI's first import does.
                spec = importlib.util.spec_from_file_location("openai_files_check", openai_files.__file__)
                module = importlib.util.module_from_spec(spec)
                env = {"OPENAI_FILES_API_BASE_URL": base_url, "OPENAI_FILES_API_MODELS_REGEX_PATTERN": pattern}
                with patch.dict(os.environ, env), self.assertLogs("openai_files_check", level="ERROR"):
                    spec.loader.exec_module(module)

                self.assertFalse(module.is_file_id_model({"id": "langflow/flow"}))


class SendImageIdsTest(FileIdsCase):
    """Stored images go by file ID too, in place of the image_url parts that show them."""

    def setUp(self) -> None:
        workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        photo = stored_file(workdir, "photo", "photo.png", "image/png")
        cached = stored_file(workdir, "cached", "scan.jpg", "image/jpeg", openai_file_id="file-cached")
        drawing = stored_file(workdir, "drawing", "drawing.svg", "image/svg+xml")
        foreign = stored_file(workdir, "foreign", "theirs.png", "image/png")
        foreign.user_id = "other-user"
        self.records = {file.id: file for file in (photo, cached, drawing, foreign)}
        # Open WebUI lists a chat image as a file and shows it as an image_url part with its ID.
        self.files = [
            {"type": "file", "id": file.id, "url": file.id, "name": file.filename, **file.meta}
            for file in self.records.values()
        ]
        self.messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Compare them."},
                    {"type": "image_url", "image_url": {"url": "photo", "detail": "high"}},
                    {"type": "image_url", "image_url": {"url": "/api/v1/files/cached/content"}},
                    {"type": "image_url", "image_url": {"url": "drawing"}},
                    {"type": "image_url", "image_url": {"url": "foreign"}},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
                ],
                "files": copy.deepcopy(self.files),
            }
        ]

    async def test_matching_models_receive_stored_images_by_file_id(self) -> None:
        api, save_id = FakeFilesApi(), AsyncMock()
        form_data, metadata = await self.send({"id": "langflow/flow"}, api, save_id)
        [message] = form_data["messages"]

        # In place and with their detail, whether the part names the file or its content URL. An
        # SVG, another user's image, and a data URL keep their parts, which Open WebUI inlines.
        self.assertEqual(
            message["content"],
            [
                {"type": "text", "text": "Compare them."},
                {"type": "input_image", "file_id": "file-1", "detail": "high"},
                {"type": "input_image", "file_id": "file-cached", "detail": "auto"},
                *self.messages[0]["content"][3:],
            ],
        )
        # Retrieval and the file tools no longer see the images sent by ID, in any list.
        for files in (message["files"], metadata["files"], form_data["files"]):
            self.assertEqual([file["id"] for file in files], ["drawing", "foreign"])

        # The image without an ID is uploaded once, as itself, and keeps its ID.
        [upload] = api.requests
        form = await parse_upload(upload)
        self.addAsyncCleanup(form.close)
        self.assertEqual((form["purpose"], form["file"].filename), ("user_data", "photo.png"))
        self.assertEqual(form["file"].content_type, "image/png")
        save_id.assert_awaited_once_with("photo", {"openai_file_id": "file-1"})

    async def test_the_attached_files_context_leaves_out_images_sent_by_id(self) -> None:
        sent, _ = await self.send({"id": "langflow/flow"}, FakeFilesApi(), AsyncMock())
        upstream, _ = await self.send({"id": "openai/gpt"}, FakeFilesApi(), AsyncMock())

        [sent_message] = middleware.add_file_context(sent["messages"])
        [upstream_message] = middleware.add_file_context(upstream["messages"])
        self.assertNotIn('id="photo"', sent_message["content"][0]["text"])
        self.assertIn('id="drawing"', sent_message["content"][0]["text"])
        self.assertIn('id="photo"', upstream_message["content"][0]["text"])

    async def test_a_failed_upload_keeps_that_image_inline(self) -> None:
        form_data, metadata = await self.send({"id": "langflow/flow"}, FakeFilesApi(upload_status=401), AsyncMock())
        [message] = form_data["messages"]

        self.assertEqual(message["content"][1], self.messages[0]["content"][1])
        self.assertIn("photo", [file["id"] for file in metadata["files"]])
        # The image with an ID is still sent by ID.
        self.assertEqual(message["content"][2], {"type": "input_image", "file_id": "file-cached", "detail": "auto"})

    async def test_other_models_keep_upstream_inline_images(self) -> None:
        api = FakeFilesApi()
        form_data, metadata = await self.send({"id": "openai/gpt"}, api, AsyncMock())

        self.assertEqual(form_data["messages"], self.messages)
        self.assertEqual(metadata["files"], self.files)
        self.assertEqual(api.requests, [])

    async def test_open_webui_does_not_inline_images_sent_by_id(self) -> None:
        part = {"type": "input_image", "file_id": "file-1", "detail": "high"}
        form_data = {"messages": [{"role": "user", "content": [part]}]}
        inline = AsyncMock(return_value="data:image/png;base64,iVBORw0KGgo=")
        with patch.object(middleware, "get_image_base64_from_url", inline):
            await middleware.convert_url_images_to_base64(form_data, user=USER)

        self.assertEqual(form_data["messages"][0]["content"], [part])
        inline.assert_not_awaited()

    def test_responses_connections_receive_images_sent_by_id(self) -> None:
        image = {"type": "input_image", "file_id": "file-1", "detail": "high"}
        messages = [{"role": "user", "content": [{"type": "text", "text": "Compare them."}, image]}]
        payload = openai.convert_to_responses_payload({"model": "langflow/flow", "messages": messages})

        self.assertEqual(payload["input"][0]["content"], [{"type": "input_text", "text": "Compare them."}, image])


class ChatPayloadTest(unittest.IsolatedAsyncioTestCase):
    """The hook inside Open WebUI's own chat request processing."""

    async def process(
        self,
        model_id: str,
        function_calling: str,
        session_id: str | None,
        file: SimpleNamespace | None = None,
        user_content: str | list = "Summarize",
    ) -> dict:
        """Process one chat request; record what retrieval, the builtin tools, and the model receive."""
        file = file or SimpleNamespace(
            id="doc",
            user_id=USER.id,
            path="/tmp/doc.pdf",
            filename="doc.pdf",
            meta={"content_type": "application/pdf", "openai_file_id": "file-doc"},
            data={"content": "DOC TEXT"},
        )
        item = {"type": "file", "id": file.id, "name": file.filename}
        model = {"id": model_id, "owned_by": "openai", "info": {"meta": {"capabilities": {"file_upload": True}}}}
        state = SimpleNamespace(MODELS={model_id: model}, RERANKING_FUNCTION=None, EMBEDDING_FUNCTION=None)
        request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(), cookies={}, headers={})
        form_data = {
            "model": model_id,
            "stream": False,
            "messages": [{"role": "user", "content": user_content, "files": [item]}],
            "files": [item],
        }
        metadata = {
            "chat_id": "",
            "message_id": "m1",
            "session_id": session_id,
            "files": form_data["files"],
            "params": {"function_calling": function_calling},
            "filter_ids": [],
            "tool_ids": None,
            "tool_servers": None,
            "features": {},
            "variables": {},
            "chat_context": {},
            "user_message": None,
            "user_message_id": None,
        }
        seen = {"retrieval": [], "tools": []}

        async def get_sources_from_items(**kwargs) -> list[dict]:
            seen["retrieval"] = [item.get("id") for item in kwargs["items"]]
            return [{"source": {"id": "doc", "name": "doc.pdf"}, "document": ["DOC TEXT"], "metadata": [{"source": "doc.pdf"}]}]

        get_builtin_tools = builtin_tools.get_builtin_tools

        async def record_builtin_tools(*args, **kwargs) -> dict:
            tools = await get_builtin_tools(*args, **kwargs)
            seen["tools"] = sorted(tools)
            return tools

        with files_api(
            FakeFilesApi(),
            patch.object(openai_files.Files, "get_files_by_ids", AsyncMock(return_value=[file])),
            patch.object(middleware, "get_event_emitter", AsyncMock(return_value=AsyncMock())),
            patch.object(middleware, "generate_queries", AsyncMock(side_effect=Exception("no task model"))),
            patch.object(middleware, "get_sources_from_items", get_sources_from_items),
            patch.object(middleware, "get_builtin_tools", record_builtin_tools),
            patch.object(builtin_tools, "has_permission", AsyncMock(return_value=True)),
        ):
            form_data, metadata, _, _ = await middleware.process_chat_payload(request, form_data, USER, metadata, model)

        content = form_data["messages"][-1]["content"]
        seen["text"] = " ".join(part.get("text", "") for part in content) if isinstance(content, list) else content
        parts = content if isinstance(content, list) else []
        seen["parts"] = [part for part in parts if part.get("type") == "file"]
        seen["images"] = [part for part in parts if part.get("type") in ("image_url", "input_image")]
        seen["files"] = [file["id"] for file in metadata.get("files") or []]
        return seen

    async def test_preloaded_file_text_leaves_out_documents_sent_by_id(self) -> None:
        sent = await self.process("langflow/flow", "legacy", None)
        upstream = await self.process("openai/gpt", "legacy", None)

        self.assertEqual(sent["parts"], [{"type": "file", "file": {"file_id": "file-doc", "filename": "doc.pdf"}}])
        self.assertEqual((sent["retrieval"], sent["files"]), ([], []))
        self.assertNotIn("DOC TEXT", sent["text"])
        # Upstream, the same request retrieves and injects the document's text.
        self.assertEqual((upstream["parts"], upstream["retrieval"]), ([], ["doc"]))
        self.assertIn("DOC TEXT", upstream["text"])

    async def test_builtin_file_tools_leave_out_documents_sent_by_id(self) -> None:
        sent = await self.process("langflow/flow", "native", "session-id")
        upstream = await self.process("openai/gpt", "native", "session-id")

        self.assertEqual(len(sent["parts"]), 1)
        self.assertFalse(CHAT_FILE_TOOLS & set(sent["tools"]), sent["tools"])
        self.assertEqual(CHAT_FILE_TOOLS & set(upstream["tools"]), CHAT_FILE_TOOLS)

    async def test_stored_images_reach_matching_models_by_id_not_inline(self) -> None:
        image = SimpleNamespace(
            id="photo",
            user_id=USER.id,
            path="/tmp/photo.png",
            filename="photo.png",
            meta={"content_type": "image/png", "openai_file_id": "file-photo"},
            data={},
        )
        content = [{"type": "text", "text": "Describe"}, {"type": "image_url", "image_url": {"url": "photo"}}]
        inline = AsyncMock(return_value="data:image/png;base64,iVBORw0KGgo=")
        with patch.object(middleware, "get_image_base64_from_url", inline):
            sent = await self.process("langflow/flow", "legacy", None, image, copy.deepcopy(content))
            upstream = await self.process("openai/gpt", "legacy", None, image, copy.deepcopy(content))

        self.assertEqual(sent["images"], [{"type": "input_image", "file_id": "file-photo", "detail": "auto"}])
        self.assertEqual(sent["files"], [])
        # Upstream, Open WebUI inlines the same image as a data URL.
        self.assertEqual(upstream["images"], [{"type": "image_url", "image_url": {"url": inline.return_value}}])


class ExtractThroughFilesApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = dict.fromkeys(retrieval.RETRIEVAL_CONFIG_KEYS.values())
        self.config.update({"rag.content_extraction_engine": "openai_files", "rag.bypass_embedding_and_retrieval": True})

    async def test_processing_uploads_the_file_and_stores_its_text_once_extracted(self) -> None:
        file = stored_file(self.workdir, "report", "report.pdf", "application/pdf")
        api = FakeFilesApi(statuses=({"status": "uploaded"}, {"status": "processed"}))
        save_id, save_data, get_file = AsyncMock(), AsyncMock(), Mock(side_effect=lambda path: path)
        with files_api(
            api,
            patch.object(retrieval.Storage, "get_file", get_file),
            patch.object(retrieval.Config, "get_many", AsyncMock(return_value=self.config)),
            patch.object(retrieval.Files, "get_file_by_id", AsyncMock(return_value=file)),
            patch.object(retrieval.Files, "update_file_metadata_by_id", save_id),
            patch.object(retrieval.Files, "update_file_data_by_id", save_data),
            patch.object(retrieval.Files, "update_file_hash_by_id", AsyncMock()),
            patch.object(retrieval, "publish_event", AsyncMock()),
        ) as clients:
            result = await retrieval.index_file(
                SimpleNamespace(client=None), retrieval.ProcessFileForm(file_id=file.id), user=USER, db=None
            )

        self.assertEqual(result["content"], MARKDOWN)
        save_data.assert_any_await(file.id, {"content": MARKDOWN}, db=None)
        save_id.assert_awaited_once_with(file.id, {"openai_file_id": "file-1"})
        # The upload reuses the local copy processing downloaded.
        get_file.assert_called_once_with(file.path)
        # The upload, a status check until the file is processed, then its extracted content.
        file_url = "/v1/files/file-1"
        self.assertEqual(
            [(request.method, request.url.path) for request in api.requests],
            [("POST", "/v1/files"), ("GET", file_url), ("GET", file_url), ("GET", f"{file_url}/content")],
        )
        for request in api.requests:
            self.assertEqual(dict(request.url.params), {"provider": "files"})
            self.assertEqual(request.headers["Authorization"], "Bearer user-token")
        self.assertEqual(clients, [{"verify": openai_files.AIOHTTP_CLIENT_SESSION_SSL}])

    def test_extracted_content_becomes_text(self) -> None:
        results = [{"md_content": "# Page 1"}, {"md_content": None}, {"md_content": "Page 2"}]
        sheets = [{"name": "A", "chunks": ["A: row 1"]}, {"name": "B", "chunks": ["B: row 1", "B: row 51"]}]
        for content, text in (
            ({"results": results}, "# Page 1\n\nPage 2"),
            ({"type": "text", "version": 1, "text": "Notes."}, "Notes."),
            ({"type": "spreadsheet", "version": 1, "sheets": sheets}, "A: row 1\n\nB: row 1\n\nB: row 51"),
        ):
            with self.subTest(text=text):
                self.assertEqual(openai_files.extracted_text(content), text)
        # Content from an engine this patch does not read yet is never stored as empty text.
        with self.assertRaisesRegex(ValueError, "transcript content"):
            openai_files.extracted_text({"type": "transcript", "version": 1, "segments": []})

    async def extract(self, api: FakeFilesApi, *patches, name: str = "report.pdf") -> list:
        """Load a stored file as processing an upload does."""
        file = stored_file(self.workdir, "report", name, "application/octet-stream")
        loader = Loader(self.config)
        loader.user, loader.request, loader.metadata = USER, SimpleNamespace(), {"file_id": file.id}
        with files_api(
            api,
            patch.object(openai_files.Files, "get_file_by_id", AsyncMock(return_value=file)),
            patch.object(openai_files.Files, "update_file_metadata_by_id", AsyncMock()),
            *patches,
        ):
            return await loader.aload(file.filename, "application/octet-stream", file.path)

    async def test_extracted_text_is_post_processed_like_any_engines(self) -> None:
        # Loader.load fixes every engine's text, here a ligature PDFs often keep.
        api = FakeFilesApi(content=httpx.Response(200, json={"results": [{"md_content": "\ufb01nal"}]}))
        docs = await self.extract(api)

        self.assertEqual([(doc.page_content, doc.metadata) for doc in docs], [("final", {"openai_file_id": "file-1"})])

    async def test_a_failed_unfinished_or_unreadable_extraction_fails_processing(self) -> None:
        failed = FakeFilesApi(statuses=({"status": "error", "status_details": "Failed to parse the file."},))
        no_url = patch.multiple(openai_files, OPENAI_FILES_API_BASE_URL="")
        no_wait = patch.multiple(openai_files, OPENAI_FILES_API_TIMEOUT=0)
        for api, patches, error, message in (
            (failed, (), ValueError, "Failed to parse"),
            (FakeFilesApi(statuses=({"status": "uploaded"},)), (no_wait,), RuntimeError, "Giving up"),
            # For example, a sign-in page a proxy answers with.
            (FakeFilesApi(content=httpx.Response(200, text="<html>Sign in</html>")), (), json.JSONDecodeError, ""),
            (FakeFilesApi(), (no_url,), ValueError, "needs OPENAI_FILES_API_BASE_URL"),
        ):
            with self.subTest(message=message or "not JSON"):
                with self.assertRaisesRegex(error, message):
                    await self.extract(api, *patches)

    async def test_other_files_and_web_downloads_use_the_built_in_loaders(self) -> None:
        api = FakeFilesApi()
        # Other files need no Files API, so not its base URL either.
        for base_url in (GATEWAY, ""):
            with self.subTest(base_url=base_url):
                setting = patch.multiple(openai_files, OPENAI_FILES_API_BASE_URL=base_url)
                docs = await self.extract(api, setting, name="notes.txt")
                self.assertEqual([doc.page_content for doc in docs], ["notes.txt bytes"])
        # Documents Open WebUI downloads from the web load synchronously, without an upload.
        path = self.workdir / "page.txt"
        path.write_text("Local text.")
        with files_api(api):
            downloaded = Loader(self.config).load("page.txt", "text/plain", str(path))

        self.assertEqual([doc.page_content for doc in downloaded], ["Local text."])
        self.assertEqual(api.requests, [])


if __name__ == "__main__":
    unittest.main()
