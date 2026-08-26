import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import Request
from openai import OpenAI

from langflow.api.v1 import openai_responses
from langflow.schema import OpenAIResponsesRequest


def _request(*headers: tuple[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("langflow", 7860),
            "client": ("127.0.0.1", 12345),
            "path": "/api/v1/responses",
            "query_string": b"",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
        }
    )


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event_name = next(line[7:] for line in lines if line.startswith("event: "))
        payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        assert payload["type"] == event_name
        events.append(payload)
    return events


class ResponsesCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_canonical_message_input(self):
        request = OpenAIResponsesRequest(
            model="FirstFlow",
            instructions="Be concise.",
            input=[
                {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "Who are you?"},
            ],
        )

        self.assertEqual(
            request.to_input_text(),
            "SYSTEM: Be concise.\n\nUSER: Hello\n\nASSISTANT: Hi\n\nUSER: Who are you?",
        )
        self.assertEqual(
            OpenAIResponsesRequest(model="FirstFlow", input="Hello").to_input_text(),
            "Hello",
        )

    async def test_accepts_openai_bearer_auth(self):
        user = SimpleNamespace(id="user-id")
        security = AsyncMock(return_value=user)

        with patch.object(openai_responses, "api_key_security", security):
            result = await openai_responses.openai_api_key_security(
                _request(("Authorization", "Bearer langflow-key"))
            )

        self.assertIs(result, user)
        security.assert_awaited_once_with(None, "langflow-key")

    async def test_emits_canonical_stream_without_duplicate_text(self):
        body = await self._stream_body(
            [
                {"event": "token", "data": {"chunk": "I"}},
                {"event": "token", "data": {"chunk": " am Langflow"}},
                {
                    "event": "add_message",
                    "data": {
                        "sender": "Machine",
                        "sender_name": "AI",
                        "text": "I am Langflow",
                        "properties": {
                            "state": "complete",
                            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
                        },
                    },
                },
            ]
        )
        events = _parse_sse(body)
        event_types = [event["type"] for event in events]

        self.assertEqual(
            event_types,
            [
                "response.created",
                "response.in_progress",
                "response.output_item.added",
                "response.content_part.added",
                "response.output_text.delta",
                "response.output_text.delta",
                "response.output_text.done",
                "response.content_part.done",
                "response.output_item.done",
                "response.completed",
            ],
        )
        self.assertEqual([event["sequence_number"] for event in events], list(range(len(events))))
        self.assertEqual(
            "".join(event["delta"] for event in events if event["type"] == "response.output_text.delta"),
            "I am Langflow",
        )
        self.assertNotIn("response.chunk", body)
        self.assertNotIn("[DONE]", body)
        completed = events[-1]["response"]
        self.assertEqual(completed["output"][0]["content"][0]["text"], "I am Langflow")
        self.assertEqual(completed["usage"]["total_tokens"], 7)

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body.encode(),
                request=request,
            )
        )
        client = OpenAI(
            api_key="test",
            base_url="http://langflow.invalid/api/v1",
            http_client=httpx.Client(transport=transport),
        )
        sdk_events = list(client.responses.create(model="FirstFlow", input="Hello", stream=True))
        self.assertEqual([event.type for event in sdk_events], event_types)

    async def test_falls_back_to_completed_message_without_tokens(self):
        body = await self._stream_body(
            [
                {
                    "event": "add_message",
                    "data": {
                        "sender": "Machine",
                        "sender_name": "AI",
                        "text": "Fallback",
                        "properties": {"state": "complete"},
                    },
                }
            ]
        )
        events = _parse_sse(body)
        deltas = [event["delta"] for event in events if event["type"] == "response.output_text.delta"]
        self.assertEqual(deltas, ["Fallback"])

    async def _stream_body(self, flow_events: list[dict]) -> str:
        async def run_flow_generator(**_kwargs):
            return None

        async def consume_and_yield(*_args):
            for event in flow_events:
                yield json.dumps(event).encode()

        flow = SimpleNamespace(
            data={
                "nodes": [
                    {"data": {"type": "ChatInput"}},
                    {"data": {"type": "ChatOutput"}},
                ]
            }
        )
        request = OpenAIResponsesRequest(model="FirstFlow", input="Hello", stream=True)
        with (
            patch.object(openai_responses, "run_flow_generator", run_flow_generator),
            patch.object(openai_responses, "consume_and_yield", consume_and_yield),
        ):
            response = await openai_responses.run_flow_for_openai_responses(
                flow=flow,
                request=request,
                api_key_user=SimpleNamespace(id="user-id"),
                stream=True,
            )
            chunks = [chunk async for chunk in response.body_iterator]
        return "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)


if __name__ == "__main__":
    unittest.main()
