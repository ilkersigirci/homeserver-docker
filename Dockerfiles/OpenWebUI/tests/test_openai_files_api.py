"""Chat documents go through an OpenAI-compatible Files API: sent by file ID or extracted there."""

import contextlib
import copy
import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import requests
from open_webui.retrieval.loaders import openai_files as files_loader
from open_webui.retrieval.loaders.main import Loader
from open_webui.routers import retrieval
from open_webui.utils import middleware, openai_files
from open_webui.utils import tools as builtin_tools
from starlette.requests import Request

GATEWAY = "https://gateway.example/v1"
USER = SimpleNamespace(id="user-id", role="user", name="User", email="user@example.com")
TOKEN = {"access_token": "user-token"}
MARKDOWN = "# Rapor\n\nÇıkarılan metin."
# The builtin tools offered for a chat's own files; display_file also serves knowledge bases.
CHAT_FILE_TOOLS = {"list_chat_files", "query_chat_files", "grep_chat_files", "view_file"}


class FakeResponse:
    def __init__(self, status: int, file_id: str) -> None:
        self.status = status
        self.file_id = file_id

    async def json(self) -> dict:
        return {"id": self.file_id, "object": "file"}

    async def text(self) -> str:
        return '{"error": {"message": "Unauthorized"}}'

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeSession:
    """Records each Files API upload and answers with a new file ID, or with an error status."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.uploads: list[dict] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.uploads.append({"url": url, **kwargs})
        return FakeResponse(self.status, f"file-{len(self.uploads)}")


async def parse_upload(upload: dict):
    """The upload's multipart form, parsed as a FastAPI Files API parses it."""
    payload = upload["data"]()
    chunks: list[bytes] = []

    class Writer:
        async def write(self, chunk: bytes) -> None:
            chunks.append(bytes(chunk))

    await payload.write(Writer())
    body = b"".join(chunks)

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", payload.content_type.encode())]
    return await Request({"type": "http", "method": "POST", "headers": headers}, receive).form()


def http_response(status: int, content_type: str, body: bytes) -> requests.Response:
    """A response as requests builds it, including its header-derived encoding."""
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = content_type
    response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    response._content = body
    return response


@contextlib.contextmanager
def files_api(session: FakeSession, *patches, token: object = TOKEN, pattern: str = "^langflow/"):
    """The image's Files API settings, behind a system_oauth connection to the same gateway."""
    connections = (True, [GATEWAY], [""], {"0": {"auth_type": "system_oauth"}})
    with contextlib.ExitStack() as stack:
        for manager in (
            patch.multiple(
                openai_files,
                ENABLE_OPENAI_FILES_API=True,
                OPENAI_FILES_API_BASE_URL=GATEWAY,
                OPENAI_FILES_API_KEY="static-key",
                OPENAI_FILES_API_PARAMS={"provider": "files"},
                OPENAI_FILES_API_MODELS_REGEX=re.compile(pattern or "(?!)"),
                OPENAI_FILES_API_TIMEOUT=300,
            ),
            patch("open_webui.routers.openai.get_openai_runtime_config", AsyncMock(return_value=connections)),
            patch("open_webui.utils.middleware.get_system_oauth_token", AsyncMock(return_value=token)),
            patch.object(openai_files, "get_session", AsyncMock(return_value=session)),
            patch.object(openai_files.Storage, "get_file", side_effect=lambda path: path),
            *patches,
        ):
            stack.enter_context(manager)
        yield


def stored_file(workdir: Path, id: str, name: str, content_type: str, **meta) -> SimpleNamespace:
    path = workdir / name
    path.write_bytes(f"{name} bytes".encode())
    return SimpleNamespace(
        id=id, user_id=USER.id, path=str(path), filename=name, meta={"content_type": content_type, **meta}, data={}
    )


class SendFileIdsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        cached = stored_file(workdir, "cached", "a.pdf", "application/pdf", openai_file_id="file-cached")
        new = stored_file(workdir, "new", 'Rapor "son" şubat 2026.docx', "application/msword")
        image = stored_file(workdir, "image", "c.png", "image/png")
        audio = stored_file(workdir, "audio", "voice.mp3", "audio/mpeg")
        foreign = stored_file(workdir, "foreign", "d.pdf", "application/pdf")
        foreign.user_id = "other-user"
        self.records = {file.id: file for file in (cached, new, image, audio, foreign)}

        def item(file: SimpleNamespace) -> dict:
            return {"type": "image" if file is image else "file", "id": file.id, "name": file.filename}

        self.messages = [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Summarize.", "files": [item(cached), item(image), item(new)]},
            {"role": "assistant", "content": "Done."},
            {
                "role": "user",
                "content": [{"type": "text", "text": "Compare."}],
                "files": [item(new), item(audio), item(foreign)],
            },
        ]
        self.files = [*(item(file) for file in self.records.values()), {"type": "collection", "id": "kb"}]

    async def send(self, model: dict, session: FakeSession, save_id: AsyncMock, **settings) -> tuple[dict, dict]:
        # As in a real request, metadata['files'] starts as the request's own files list.
        form_data = {"messages": copy.deepcopy(self.messages), "files": copy.deepcopy(self.files)}
        metadata = {"files": form_data["files"]}
        get_files = AsyncMock(side_effect=lambda ids: [self.records[id] for id in ids])
        with files_api(
            session,
            patch.object(openai_files.Files, "get_files_by_ids", get_files),
            patch.object(openai_files.Files, "update_file_metadata_by_id", save_id),
            patch.object(openai_files, "has_access_to_file", AsyncMock(return_value=False)),
            **settings,
        ):
            await openai_files.add_file_id_parts(SimpleNamespace(), form_data, metadata, USER, model)
        return form_data, metadata

    async def test_matching_models_receive_each_message_documents_by_file_id(self) -> None:
        session, save_id = FakeSession(), AsyncMock()
        form_data, metadata = await self.send({"id": "langflow/flow"}, session, save_id)
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
        # Images, audio, and another user's file keep Open WebUI's usual handling.
        self.assertEqual([file["id"] for file in first["files"]], ["image"])
        self.assertEqual([file["id"] for file in second["files"]], ["audio", "foreign"])
        # Retrieval and the file tools no longer see the documents sent by ID, in either list.
        for files in (metadata["files"], form_data["files"]):
            self.assertEqual([file["id"] for file in files], ["image", "audio", "foreign", "kb"])

        # The file without an ID is uploaded once, though two messages attach it, and keeps its ID.
        [upload] = session.uploads
        self.assertEqual(upload["url"], f"{GATEWAY}/files")
        self.assertEqual(upload["params"], {"provider": "files"})
        self.assertEqual(upload["headers"]["Authorization"], "Bearer user-token")
        self.assertEqual(upload["timeout"].total, 300)
        save_id.assert_awaited_once_with("new", {"openai_file_id": "file-1"})

    async def test_the_files_api_receives_the_file_and_its_name_as_is(self) -> None:
        session = FakeSession()
        await self.send({"id": "langflow/flow"}, session, AsyncMock())

        form = await parse_upload(session.uploads[0])
        self.addAsyncCleanup(form.close)
        self.assertEqual(form["purpose"], "user_data")
        self.assertEqual(form["file"].filename, 'Rapor "son" şubat 2026.docx')
        self.assertEqual(await form["file"].read(), 'Rapor "son" şubat 2026.docx bytes'.encode())

    async def test_a_failed_upload_keeps_that_document_on_open_webui_handling(self) -> None:
        # Without an OAuth session, the upload carries no token, never the key, and is refused.
        session = FakeSession(status=401)
        form_data, metadata = await self.send({"id": "langflow/flow"}, session, AsyncMock(), token=None)
        _, first, _, second = form_data["messages"]

        self.assertEqual(session.uploads[0]["headers"]["Authorization"], "Bearer ")
        self.assertEqual(second["content"], [{"type": "text", "text": "Compare."}])
        self.assertEqual([file["id"] for file in second["files"]], ["new", "audio", "foreign"])
        # The document with an ID is still sent by ID.
        self.assertEqual(first["content"][-1]["file"]["file_id"], "file-cached")
        self.assertIn("new", [file["id"] for file in metadata["files"]])

    async def test_workspace_models_match_through_their_base_model(self) -> None:
        model = {"id": "my-assistant", "info": {"base_model_id": "langflow/flow"}}
        form_data, _ = await self.send(model, FakeSession(), AsyncMock())

        self.assertEqual(form_data["messages"][3]["content"][-1]["file"]["file_id"], "file-1")

    async def test_other_models_and_an_empty_pattern_keep_upstream_behavior(self) -> None:
        for model_id, pattern in (("openai/gpt", "^langflow/"), ("langflow/flow", "")):
            with self.subTest(model_id=model_id, pattern=pattern):
                session = FakeSession()
                form_data, metadata = await self.send({"id": model_id}, session, AsyncMock(), pattern=pattern)

                self.assertEqual(form_data["messages"], self.messages)
                self.assertEqual(metadata["files"], self.files)
                self.assertEqual(session.uploads, [])

    def test_an_invalid_pattern_turns_file_ids_off(self) -> None:
        # A fresh copy of the module reads the settings, as Open WebUI's first import does.
        spec = importlib.util.spec_from_file_location("openai_files_check", openai_files.__file__)
        module = importlib.util.module_from_spec(spec)
        env = {
            "ENABLE_OPENAI_FILES_API": "true",
            "OPENAI_FILES_API_BASE_URL": GATEWAY,
            "OPENAI_FILES_API_MODELS_REGEX_PATTERN": "^langflow/(",
        }
        with patch.dict(os.environ, env), self.assertLogs("openai_files_check", level="ERROR"):
            spec.loader.exec_module(module)

        self.assertFalse(module.is_file_id_model({"id": "langflow/flow"}))


class ChatPayloadTest(unittest.IsolatedAsyncioTestCase):
    """The hook inside Open WebUI's own chat request processing."""

    async def process(self, model_id: str, function_calling: str, session_id: str | None) -> dict:
        """Process one chat request; record what retrieval, the builtin tools, and the model receive."""
        document = SimpleNamespace(
            id="doc",
            user_id=USER.id,
            path="/tmp/doc.pdf",
            filename="doc.pdf",
            meta={"content_type": "application/pdf", "openai_file_id": "file-doc"},
            data={"content": "DOC TEXT"},
        )
        item = {"type": "file", "id": "doc", "name": "doc.pdf"}
        model = {"id": model_id, "owned_by": "openai", "info": {"meta": {"capabilities": {"file_upload": True}}}}
        state = SimpleNamespace(MODELS={model_id: model}, RERANKING_FUNCTION=None, EMBEDDING_FUNCTION=None)
        request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(), cookies={}, headers={})
        form_data = {
            "model": model_id,
            "stream": False,
            "messages": [{"role": "user", "content": "Summarize", "files": [item]}],
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
            FakeSession(),
            patch.object(openai_files.Files, "get_files_by_ids", AsyncMock(return_value=[document])),
            patch.object(middleware, "get_event_emitter", AsyncMock(return_value=AsyncMock())),
            patch.object(middleware, "generate_queries", AsyncMock(side_effect=Exception("no task model"))),
            patch.object(middleware, "get_sources_from_items", get_sources_from_items),
            patch.object(middleware, "get_builtin_tools", record_builtin_tools),
            patch.object(builtin_tools, "has_permission", AsyncMock(return_value=True)),
        ):
            form_data, metadata, _, _ = await middleware.process_chat_payload(request, form_data, USER, metadata, model)

        content = form_data["messages"][-1]["content"]
        seen["text"] = " ".join(part.get("text", "") for part in content) if isinstance(content, list) else content
        seen["parts"] = [part for part in content if part.get("type") == "file"] if isinstance(content, list) else []
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


class ExtractThroughFilesApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workdir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = dict.fromkeys(retrieval.RETRIEVAL_CONFIG_KEYS.values())
        self.config.update({"rag.content_extraction_engine": "openai_files", "rag.bypass_embedding_and_retrieval": True})

    async def test_processing_uploads_the_file_and_stores_its_extracted_text(self) -> None:
        file = stored_file(self.workdir, "report", "report.pdf", "application/pdf")
        session, save_id, save_data = FakeSession(), AsyncMock(), AsyncMock()
        # Without a charset, the text is UTF-8.
        get = Mock(return_value=http_response(200, "text/markdown", MARKDOWN.encode()))
        with files_api(
            session,
            patch.object(retrieval.Config, "get_many", AsyncMock(return_value=self.config)),
            patch.object(retrieval.Files, "get_file_by_id", AsyncMock(return_value=file)),
            patch.object(retrieval.Files, "update_file_metadata_by_id", save_id),
            patch.object(retrieval.Files, "update_file_data_by_id", save_data),
            patch.object(retrieval.Files, "update_file_hash_by_id", AsyncMock()),
            patch.object(retrieval, "publish_event", AsyncMock()),
            patch.object(files_loader.requests, "get", get),
        ):
            result = await retrieval.index_file(
                SimpleNamespace(client=None), retrieval.ProcessFileForm(file_id=file.id), user=USER, db=None
            )

        self.assertEqual(result["content"], MARKDOWN)
        save_data.assert_any_await(file.id, {"content": MARKDOWN}, db=None)
        [upload] = session.uploads
        self.assertEqual(upload["headers"]["Authorization"], "Bearer user-token")
        save_id.assert_awaited_once_with(file.id, {"openai_file_id": "file-1"})
        self.assertEqual(get.call_args.args, (f"{GATEWAY}/files/file-1/content",))
        self.assertEqual(get.call_args.kwargs["params"], {"provider": "files", "format": "markdown"})
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer user-token")
        self.assertEqual(get.call_args.kwargs["timeout"], (10, 300))
        self.assertIs(get.call_args.kwargs["verify"], files_loader.REQUESTS_VERIFY)

    def test_only_extracted_text_becomes_the_document_text(self) -> None:
        loader = files_loader.OpenAIFilesLoader(GATEWAY, "file-1", {}, {}, 300)
        for response in (
            http_response(200, "application/pdf", b"%PDF-1.7"),
            # For example, a sign-in page a proxy answers with.
            http_response(200, "text/html; charset=utf-8", b"<html>Sign in</html>"),
            http_response(415, "application/json", b'{"error": {"message": "Unsupported file type"}}'),
        ):
            with (
                self.subTest(status=response.status_code, content_type=response.headers["Content-Type"]),
                patch.object(files_loader.requests, "get", Mock(return_value=response)),
            ):
                with self.assertRaises(ValueError):
                    loader.load()

    async def test_without_the_files_api_the_built_in_loaders_extract(self) -> None:
        path = self.workdir / "notes.txt"
        path.write_text("Local text.")
        with patch.multiple(openai_files, ENABLE_OPENAI_FILES_API=False):
            processed = await Loader(self.config).aload("notes.txt", "text/plain", str(path))
        # Documents Open WebUI downloads from the web load synchronously, without an upload.
        downloaded = Loader(self.config).load("notes.txt", "text/plain", str(path))

        for docs in (processed, downloaded):
            self.assertEqual([doc.page_content for doc in docs], ["Local text."])


if __name__ == "__main__":
    unittest.main()
