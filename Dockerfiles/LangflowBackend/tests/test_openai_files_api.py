import json
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import SecretStr

from lfx.components.data_source import api_request
from lfx.components.input_output.chat import ChatInput
from lfx.components.input_output.chat_output import ChatOutput
from lfx.custom.directory_reader.utils import abuild_custom_component_list_from_path
from lfx.custom.eval import eval_custom_component_code
from lfx.graph.graph.base import Graph
from lfx.schema.data import Data
from lfx.schema.message import Message


COMPONENTS_PATH = Path(os.environ["LANGFLOW_COMPONENTS_PATH"])


class OpenaiFilesAPITests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = (COMPONENTS_PATH / "responses/openai_files_api.py").read_text()
        cls.component_class = eval_custom_component_code(cls.code)

    def component(self, file_ids, message=None, **kwargs):
        return self.component_class(
            _code=self.code,
            message=message if message is not None else Message(text="Summarize", sender="User"),
            responses_input=Data(data={"file_ids": file_ids}),
            **kwargs,
        )

    @contextmanager
    def http(self, handler):
        with (
            patch.object(api_request, "validate_and_resolve_url", side_effect=lambda url: (url, [])) as validate,
            patch.object(
                api_request.APIRequestComponent,
                "_build_http_client",
                side_effect=lambda *_: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            ) as client,
        ):
            yield validate, client

    async def test_empty_ids_preserve_original_message_without_http_or_settings(self):
        for files in ([], ["playground/document.txt"]):
            with self.subTest(files=files):
                message = Message(text="Question", files=files, sender="User", session_id="session-1")
                with patch.object(api_request.APIRequestComponent, "make_api_request") as request:
                    output = await self.component([], message).build_message()
                self.assertIs(output, message)
                self.assertEqual(output.files, files)
                request.assert_not_called()

    async def test_fetches_distinct_ids_and_preserves_input(self):
        message = Message(
            content_blocks=[{"type": "text", "text": "Compare"}],
            sender="User",
            session_id="session-1",
            files=["playground/document.txt"],
            session_metadata={"example": {"value": "original"}},
        )
        before = message.model_dump()
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"text": "Content café", "pages": [1, 2]})

        component = self.component(
            ["file-first", "file-second", "file-first"],
            message,
            api_base="https://files.example.com/v1/",
            api_key=SecretStr("test-token"),
            timeout=7,
        )
        with self.http(respond) as (validate, _client):
            output = await component.build_message()

        self.assertEqual(validate.call_count, 2)
        self.assertEqual(
            [str(request.url) for request in requests],
            ["https://files.example.com/v1/files/file-first/content", "https://files.example.com/v1/files/file-second/content"],
        )
        for request in requests:
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["Authorization"], "Bearer test-token")
            self.assertEqual(request.headers["Accept"], "application/json")
            self.assertEqual(request.extensions["timeout"]["read"], 7)
        self.assertIsNot(output, message)
        self.assertIsInstance(output, Message)
        self.assertEqual(message.model_dump(), before)
        self.assertTrue(output.text.startswith("Compare\n\n"))
        self.assertEqual(output.files, message.files)
        self.assertIsNot(output.files, message.files)
        self.assertEqual(output.session_metadata, message.session_metadata)
        self.assertIsNot(output.session_metadata, message.session_metadata)
        self.assertEqual(output.session_id, message.session_id)
        self.assertEqual(output.sender, "User")
        documents = json.loads(output.text.split("File contents (JSON):\n", 1)[1])
        self.assertEqual([item["file_id"] for item in documents], ["file-first", "file-second"])
        self.assertEqual(documents[0]["content"], {"text": "Content café", "pages": [1, 2]})

    async def test_encodes_file_id_as_one_path_segment(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"text": "Content"})

        with self.http(respond):
            await self.component(["file a/b?#"], api_base="https://files.example.com/v1").build_message()
        self.assertEqual(requests[0].url.raw_path, b"/v1/files/file%20a%2Fb%3F%23/content")
        self.assertNotIn("Authorization", requests[0].headers)

    async def test_http_errors_redirects_and_non_json_stop_execution(self):
        responses = [
            httpx.Response(401, json={"error": "unauthorized"}),
            httpx.Response(404, json={"error": "missing file"}),
            httpx.Response(500, json={"error": "unavailable"}),
            httpx.Response(302, headers={"Location": "https://another.example.com/content"}),
            httpx.Response(200, text="not JSON"),
            httpx.Response(200, content=b"binary", headers={"Content-Type": "application/octet-stream"}),
        ]
        for response in responses:
            with self.subTest(status=response.status_code, body=response.content):
                with self.http(lambda _request: response) as (_validate, client):
                    with self.assertRaises(ValueError):
                        await self.component(["file-1"], api_base="https://files.example.com/v1").build_message()
                self.assertEqual(client.call_count, 1)

    async def test_network_policy_denial_is_not_bypassed(self):
        with (
            patch.object(
                api_request, "validate_and_resolve_url", side_effect=api_request.SSRFProtectionError("blocked")
            ),
            patch.object(api_request.APIRequestComponent, "_build_http_client") as client,
            self.assertRaisesRegex(ValueError, "SSRF Protection"),
        ):
            await self.component(["file-1"], api_base="https://files.example.com/v1").build_message()
        client.assert_not_called()

    async def test_rejects_invalid_ids_and_missing_base_before_http(self):
        with patch.object(api_request.APIRequestComponent, "make_api_request") as request:
            for ids in (None, "file-1", [42], [""], [" "], ["."], [".."]):
                with self.subTest(ids=ids), self.assertRaises(ValueError):
                    await self.component(ids, api_base="https://files.example.com/v1").build_message()
            with self.assertRaisesRegex(ValueError, "Base URL is required"):
                await self.component(["file-1"]).build_message()
            missing_ids = self.component([]).set(responses_input=Data(data={"file_id": "file-1"}))
            with self.assertRaisesRegex(ValueError, "list of non-empty file IDs"):
                await missing_ids.build_message()
        request.assert_not_called()

    async def test_component_is_discoverable(self):
        menu = await abuild_custom_component_list_from_path(str(COMPONENTS_PATH))
        component = menu["responses"]["OpenaiFilesAPI"]
        self.assertEqual(component["display_name"], "OpenaiFilesAPI")
        self.assertEqual(component["outputs"][0]["types"], ["Message"])

    async def test_serialized_graph_receives_context_and_resets_between_requests(self):
        responses_code = (COMPONENTS_PATH / "responses/responses_input.py").read_text()
        responses = eval_custom_component_code(responses_code)(_code=responses_code)
        chat = ChatInput(should_store_message=False)
        context = self.component_class(_code=self.code, api_base="https://files.example.com/v1")
        context.set(message=chat.message_response, responses_input=responses.read_input)
        output = ChatOutput(should_store_message=False)
        output.set(input_value=context.build_message)
        payload = Graph(start=chat, end=output).dump()["data"]

        for graph_context in (
            {"responses_input": [{"role": "user", "content": [{"type": "input_file", "file_id": "file-1"}]}]},
            {},
        ):
            with self.subTest(context=graph_context):
                graph = Graph.from_payload(payload, context=graph_context)
                input_text = "" if graph_context else "Question"
                with self.http(lambda _request: httpx.Response(200, json={"text": "File content"})) as (_, client):
                    result = await graph.arun(inputs=[{"input_value": input_text}], outputs=[output.get_id()])
                text = result[0].outputs[0].results["message"].text
                if graph_context:
                    self.assertIn("File content", text)
                    self.assertEqual(client.call_count, 1)
                else:
                    self.assertEqual(text, "Question")
                    client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
