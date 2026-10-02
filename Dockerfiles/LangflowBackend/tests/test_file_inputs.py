import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from langflow.api.v1 import openai_responses
from langflow.schema import OpenAIResponsesRequest
from lfx.custom.directory_reader.utils import abuild_custom_component_list_from_path
from lfx.custom.eval import eval_custom_component_code


COMPONENTS_PATH = Path(os.environ["LANGFLOW_COMPONENTS_PATH"])


class FileInputTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        code = (COMPONENTS_PATH / "responses/responses_input.py").read_text()
        cls.component_class = eval_custom_component_code(code)

    def read_context(self, context):
        component = self.component_class()
        component.set_vertex(SimpleNamespace(graph=SimpleNamespace(context=context)))
        return component.read_input().data

    def test_file_only_input_keeps_ids_out_of_chat_text(self):
        request = OpenAIResponsesRequest(
            model="FirstFlow",
            input=[{"role": "user", "content": [{"type": "input_file", "file_id": "file-only"}]}],
        )
        self.assertEqual(request.to_input_text(), "")
        self.assertEqual(self.read_context({"responses_input": request.input})["file_ids"], ["file-only"])

    def test_rejects_malformed_and_unsupported_file_inputs(self):
        parts = [
            {"type": "input_file"},
            {"type": "input_file", "file_id": None},
            {"type": "input_file", "file_id": 42},
            {"type": "input_file", "file_id": ""},
            {"type": "input_file", "file_id": "  "},
            {"type": "input_file", "file_url": "https://example.com/document.pdf"},
            {"type": "input_file", "file_data": "data:application/pdf;base64,AA=="},
            {"type": "input_file", "file_id": "file-1", "file_url": "https://example.com/document.pdf"},
            {"type": "input_file", "file_id": "file-1", "file_data": "AA=="},
            {"type": "input_image", "image_url": "https://example.com/image.png"},
        ]
        for part in parts:
            with self.subTest(part=part), self.assertRaises(ValueError):
                OpenAIResponsesRequest(
                    model="FirstFlow", input=[{"role": "user", "content": [part]}]
                ).to_input_text()

    async def test_invalid_file_inputs_return_http_400_before_execution(self):
        app = FastAPI()
        app.include_router(openai_responses.router, prefix="/api/v1")
        user = SimpleNamespace(id="flow-owner")
        flow = SimpleNamespace(
            id="flow-id",
            user_id=user.id,
            data={"nodes": [{"data": {"type": "ChatInput"}}, {"data": {"type": "ChatOutput"}}]},
        )
        app.dependency_overrides[openai_responses.openai_api_key_security] = lambda: user
        app.dependency_overrides[openai_responses.get_telemetry_service] = lambda: SimpleNamespace()
        with (
            patch.object(openai_responses, "get_flow_by_id_or_endpoint_name", AsyncMock(return_value=flow)),
            patch.object(openai_responses, "ensure_flow_permission", AsyncMock()),
            patch.object(openai_responses, "resolve_serving_scope"),
            patch.object(openai_responses, "simple_run_flow", AsyncMock()) as run,
            patch.object(openai_responses, "run_flow_generator", AsyncMock()) as stream_run,
            patch.object(openai_responses.logger, "aerror", AsyncMock()),
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://langflow") as client:
                for stream in (False, True):
                    with self.subTest(stream=stream):
                        response = await client.post(
                            "/api/v1/responses",
                            json={
                                "model": flow.id,
                                "stream": stream,
                                "input": [{"role": "user", "content": [{"type": "input_file", "file_id": ""}]}],
                            },
                        )
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response.json()["error"]["type"], "invalid_request_error")
                        self.assertEqual(response.json()["error"]["code"], "invalid_flow_request")
            run.assert_not_awaited()
            stream_run.assert_not_awaited()

    async def test_context_reaches_components_in_both_execution_modes(self):
        input_items = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "First document"},
                    {"type": "input_file", "file_id": "file-first"},
                ],
            },
            {"role": "assistant", "content": "Ready"},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Compare these"},
                    {"type": "input_file", "file_id": "file-second"},
                    {"type": "input_file", "file_id": "file-first"},
                ],
            },
        ]
        flow = SimpleNamespace(
            user_id="flow-owner",
            data={"nodes": [{"data": {"type": "ChatInput"}}, {"data": {"type": "ChatOutput"}}]},
        )
        for stream in (False, True):
            for input_value in (input_items, "Next question"):
                with self.subTest(stream=stream, input=input_value):
                    completed = asyncio.Event()
                    observed = {}

                    async def execute(**kwargs):
                        observed["chat_text"] = kwargs["input_request"].input_value
                        observed["variables"] = kwargs["context"]["request_variables"]
                        observed["data"] = self.read_context(kwargs["context"])
                        completed.set()
                        return SimpleNamespace(outputs=[])

                    async def consume(*_args):
                        await asyncio.wait_for(completed.wait(), timeout=5)
                        yield json.dumps({"event": "token", "data": {"chunk": "Done"}}).encode()

                    request = OpenAIResponsesRequest(model="FirstFlow", input=input_value)
                    with (
                        patch.object(openai_responses, "simple_run_flow", execute),
                        patch.object(openai_responses, "run_flow_generator", execute),
                        patch.object(openai_responses, "consume_and_yield", consume),
                    ):
                        response = await openai_responses.run_flow_for_openai_responses(
                            flow=flow,
                            request=request,
                            api_key_user=SimpleNamespace(id="flow-owner"),
                            stream=stream,
                            variables={"EXAMPLE": "value"},
                        )
                        if stream:
                            async for _chunk in response.body_iterator:
                                pass

                    self.assertEqual(observed["data"]["input"], input_value)
                    self.assertEqual(observed["variables"], {"EXAMPLE": "value"})
                    if isinstance(input_value, list):
                        self.assertEqual(
                            observed["chat_text"],
                            "USER: First document\n\nASSISTANT: Ready\n\nUSER: Compare these",
                        )
                        self.assertEqual(observed["data"]["file_ids"], ["file-first", "file-second", "file-first"])
                    else:
                        self.assertEqual(observed["chat_text"], "Next question")
                        self.assertEqual(observed["data"]["file_ids"], [])

    def test_component_output_does_not_mutate_request_context(self):
        context = {"responses_input": [{"role": "user", "content": [{"type": "input_file", "file_id": "file-1"}]}]}
        result = self.read_context(context)
        result["input"][0]["content"][0]["file_id"] = "changed"
        self.assertEqual(context["responses_input"][0]["content"][0]["file_id"], "file-1")

    def test_component_outside_responses_has_no_file_references(self):
        self.assertEqual(self.read_context({}), {"input": [], "file_ids": []})

    async def test_component_is_discoverable(self):
        menu = await abuild_custom_component_list_from_path(str(COMPONENTS_PATH))
        component = menu["responses"]["ResponsesInput"]
        self.assertEqual(component["display_name"], "Responses Input")
        self.assertEqual(component["outputs"][0]["types"], ["JSON"])


if __name__ == "__main__":
    unittest.main()
