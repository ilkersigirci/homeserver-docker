import json
import unittest
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, Request
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
    def test_splits_canonical_message_input(self):
        request = OpenAIResponsesRequest(
            model="FirstFlow",
            instructions="Be concise.",
            input=[
                {"role": "developer", "content": "Answer in English."},
                {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
                {"role": "assistant", "content": [{"type": "output_text", "text": "Hi"}]},
                {"role": "user", "content": "Who are you?"},
            ],
        )

        self.assertEqual(
            request.to_conversation(),
            ("Be concise.\n\nAnswer in English.", [("user", "Hello"), ("assistant", "Hi")], "Who are you?"),
        )
        self.assertEqual(
            OpenAIResponsesRequest(model="FirstFlow", input="Hello").to_conversation(),
            ("", [], "Hello"),
        )
        for input_value in ([], [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]):
            with self.subTest(input=input_value), self.assertRaises(ValueError):
                OpenAIResponsesRequest(model="FirstFlow", input=input_value).to_conversation()

    async def test_stores_earlier_turns_in_the_run_session(self):
        flow = SimpleNamespace(id="flow-id")
        user = SimpleNamespace(id="user-id")
        history = [("user", "Hello"), ("user", ""), ("assistant", "Hi")]
        calls = []
        db = SimpleNamespace(exec=AsyncMock(side_effect=lambda _statement: calls.append("delete")))
        store = AsyncMock(side_effect=lambda *_args, **_kwargs: calls.append("add"))

        @asynccontextmanager
        async def session_scope():
            yield db

        async def store_history(*, replace, http_request=None):
            await openai_responses._store_history(
                history,
                flow=flow,
                api_key_user=user,
                session_id="session-id",
                http_request=http_request,
                replace=replace,
            )

        with (
            patch.object(openai_responses, "session_scope", session_scope),
            patch.object(openai_responses, "aadd_messages", store),
        ):
            for replace in (False, True):
                with self.subTest(replace=replace):
                    calls.clear()
                    await store_history(replace=replace)

                    messages = store.call_args.args[0]
                    self.assertEqual(
                        [(item.sender, item.sender_name, item.text, item.session_id) for item in messages],
                        [("User", "User", "Hello", "session-id"), ("Machine", "AI", "Hi", "session-id")],
                    )
                    self.assertLess(messages[0].timestamp, messages[1].timestamp)
                    self.assertEqual(store.call_args.kwargs, {"flow_id": "flow-id", "user_id": "user-id"})
                    self.assertEqual(calls, ["delete", "add"] if replace else ["add"])
            # Replacing removes only this session's messages for this flow and caller.
            statement = db.exec.call_args.args[0]
            self.assertEqual(sorted(statement.compile().params.values()), ["flow-id", "session-id", "user-id"])

            # End-user scoping would move the run to another session and owner.
            calls.clear()
            with (
                patch.object(openai_responses, "resolve_serving_scope", return_value=SimpleNamespace()),
                self.assertRaises(ValueError),
            ):
                await store_history(replace=True, http_request=_request())
            self.assertEqual(calls, [])

    async def test_session_header_selects_the_session(self):
        flow = SimpleNamespace(
            id="flow-id",
            user_id="user-id",
            data={"nodes": [{"data": {"type": "ChatInput"}}, {"data": {"type": "ChatOutput"}}]},
        )
        header = ("X-Langflow-Session-Id", "chat-1")
        for headers, fields, session_id, mirrored in (
            ([header], {}, "chat-1", True),
            ([header], {"previous_response_id": "response-1"}, "response-1", False),
            ([("X-Langflow-Session-Id", "")], {}, None, False),
            ([], {}, None, False),
        ):
            run = AsyncMock(return_value=SimpleNamespace(outputs=[]))
            with (
                self.subTest(headers=headers, fields=fields),
                patch.object(openai_responses, "_store_history", AsyncMock()) as store,
                patch.object(openai_responses, "simple_run_flow", run),
            ):
                response = await openai_responses.run_flow_for_openai_responses(
                    flow=flow,
                    request=OpenAIResponsesRequest(model="FirstFlow", input="Hello", **fields),
                    api_key_user=SimpleNamespace(id="user-id"),
                    http_request=_request(*headers),
                )

                run_session_id = run.call_args.kwargs["input_request"].session_id
                if session_id is None:
                    self.assertEqual(str(uuid.UUID(run_session_id)), run_session_id)
                else:
                    self.assertEqual(run_session_id, session_id)
                self.assertEqual(store.call_args.kwargs["session_id"], run_session_id)
                self.assertIs(store.call_args.kwargs["replace"], mirrored)
                # Gateways log each response by ID, so every turn of a mirrored chat needs its own.
                if mirrored:
                    self.assertNotEqual(response.id, run_session_id)
                    self.assertEqual(str(uuid.UUID(response.id)), response.id)
                else:
                    self.assertEqual(response.id, run_session_id)

    async def test_ignores_global_variable_headers(self):
        # Gateways forward caller headers, which must not override the flow owner's variables.
        app = FastAPI()
        app.include_router(openai_responses.router, prefix="/api/v1")
        user = SimpleNamespace(id="user-id")
        flow = SimpleNamespace(
            id="flow-id",
            user_id=user.id,
            data={"nodes": [{"data": {"type": "ChatInput"}}, {"data": {"type": "ChatOutput"}}]},
        )
        telemetry = SimpleNamespace(log_package_run=AsyncMock())
        app.dependency_overrides[openai_responses.openai_api_key_security] = lambda: user
        app.dependency_overrides[openai_responses.get_telemetry_service] = lambda: telemetry
        run = AsyncMock(return_value=SimpleNamespace(outputs=[]))
        with (
            patch.object(openai_responses, "get_flow_by_id_or_endpoint_name", AsyncMock(return_value=flow)),
            patch.object(openai_responses, "ensure_flow_permission", AsyncMock()),
            patch.object(openai_responses, "resolve_serving_scope", return_value=None),
            patch.object(openai_responses, "simple_run_flow", run),
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://langflow") as client:
                response = await client.post(
                    "/api/v1/responses",
                    json={"model": flow.id, "input": "Hello"},
                    headers={"X-LANGFLOW-GLOBAL-VAR-API_URL": "https://attacker.example"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("request_variables", run.call_args.kwargs["context"])

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

    async def test_streaming_exception_does_not_expose_raw_details(self):
        raw_error = RuntimeError("database password=super-secret")

        with patch.object(openai_responses.logger, "aexception", new_callable=AsyncMock) as log_exception:
            body = await self._stream_body(raw_error)

        events = _parse_sse(body)
        error = events[-1]
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["message"], "Workflow execution failed.")
        self.assertNotIn(str(raw_error), body)
        log_exception.assert_awaited_once_with("Error in OpenAI Responses stream generator")

    async def _stream_body(self, flow_events: list[dict] | Exception) -> str:
        async def run_flow_generator(**_kwargs):
            return None

        async def consume_and_yield(*_args):
            if isinstance(flow_events, Exception):
                raise flow_events
            for event in flow_events:
                yield json.dumps(event).encode()

        flow = SimpleNamespace(
            user_id="flow-owner-id",
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
