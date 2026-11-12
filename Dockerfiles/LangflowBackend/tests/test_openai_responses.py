import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import httpx
from fastapi import Depends, FastAPI, Request
from openai import OpenAI
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseErrorEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseInProgressEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)

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


def _validate_events(events: list[dict], models: list[type]) -> None:
    """Validate each event against its OpenAI SDK model, which is the wire schema."""
    assert [event["sequence_number"] for event in events] == list(range(len(events)))
    for event, model in zip(events, models, strict=True):
        if model is ResponseCompletedEvent:
            # Langflow reports input, output, and total tokens only, not the token details.
            event = {**event, "response": {**event["response"], "usage": None}}
        model.model_validate(event)


def _sdk_final_response(body: str):
    """Consume the stream with the OpenAI SDK's own event accumulator."""
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
    with client.responses.stream(model="FirstFlow", input="Hello") as stream:
        for _event in stream:
            pass
        return stream.get_final_response()


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
        delete = AsyncMock(side_effect=lambda *_args, **_kwargs: calls.append("delete"))
        store = AsyncMock(side_effect=lambda *_args, **_kwargs: calls.append("add"))

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
            patch.object(openai_responses, "adelete_messages", delete),
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
            self.assertEqual(delete.call_args_list, [call("session-id", flow_id="flow-id", user_id="user-id")])

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
            # The header keeps naming the conversation; the input then holds only new turns.
            ([header], {"previous_response_id": "response-1"}, "chat-1", False),
            ([], {"previous_response_id": "response-1"}, "response-1", False),
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
                # Gateways log each response by ID, so every turn of a header-named chat needs its own.
                if session_id == "chat-1":
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
        app = FastAPI()

        @app.get("/user")
        async def current_user(user=Depends(openai_responses.openai_api_key_security)):
            return {"id": user.id}

        security = AsyncMock(return_value=SimpleNamespace(id="user-id"))
        with patch.object(openai_responses, "api_key_security", security):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://langflow") as client:
                for headers, key in (
                    ({"Authorization": "Bearer langflow-key"}, "langflow-key"),
                    # Langflow's own header keeps precedence.
                    ({"x-api-key": "native-key", "Authorization": "Bearer other-key"}, "native-key"),
                ):
                    with self.subTest(headers=headers):
                        security.reset_mock()
                        response = await client.get("/user", headers=headers)
                        self.assertEqual(response.json(), {"id": "user-id"})
                        security.assert_awaited_once_with(None, key)

    async def test_emits_canonical_stream_without_duplicate_text(self):
        # Chat Output publishes its first chunk as a partial message and then as a token
        # (langflow-ai/langflow#10719); the client must receive that chunk once.
        body = await self._stream_body(
            [
                {
                    "event": "add_message",
                    "data": {
                        "id": "message-1",
                        "sender": "Machine",
                        "sender_name": "AI",
                        "text": "I",
                        "properties": {"state": "partial"},
                    },
                },
                {"event": "token", "data": {"id": "message-1", "chunk": "I"}},
                {"event": "token", "data": {"id": "message-1", "chunk": " am Langflow"}},
                {
                    "event": "add_message",
                    "data": {
                        "id": "message-1",
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
        _validate_events(
            events,
            [
                ResponseCreatedEvent,
                ResponseInProgressEvent,
                ResponseOutputItemAddedEvent,
                ResponseContentPartAddedEvent,
                ResponseTextDeltaEvent,
                ResponseTextDeltaEvent,
                ResponseTextDoneEvent,
                ResponseContentPartDoneEvent,
                ResponseOutputItemDoneEvent,
                ResponseCompletedEvent,
            ],
        )
        self.assertEqual(
            "".join(event["delta"] for event in events if event["type"] == "response.output_text.delta"),
            "I am Langflow",
        )
        final = _sdk_final_response(body)
        self.assertEqual(final.output_text, "I am Langflow")
        self.assertEqual(final.usage.total_tokens, 7)

    async def test_flow_tool_calls_stay_private_unless_included(self):
        # OpenAI clients run every function_call they receive, but the flow already ran its tools.
        step = {"type": "tool_use", "name": "search", "tool_input": {"query": "Langflow"}, "output": "Found"}
        flow_events = [
            {"event": "token", "data": {"id": "message-1", "chunk": "Found it"}},
            {
                "event": "add_message",
                "data": {
                    "id": "message-1",
                    "sender": "Machine",
                    "sender_name": "AI",
                    "text": "Found it",
                    "properties": {"state": "complete"},
                    "content_blocks": [{"title": "Agent Steps", "contents": [step]}],
                },
            },
        ]
        body = await self._stream_body(flow_events)
        _validate_events(
            _parse_sse(body),
            [
                ResponseCreatedEvent,
                ResponseInProgressEvent,
                ResponseOutputItemAddedEvent,
                ResponseContentPartAddedEvent,
                ResponseTextDeltaEvent,
                ResponseTextDoneEvent,
                ResponseContentPartDoneEvent,
                ResponseOutputItemDoneEvent,
                ResponseCompletedEvent,
            ],
        )
        final = _sdk_final_response(body)
        self.assertEqual([item.type for item in final.output], ["message"])
        self.assertEqual(final.output_text, "Found it")

        # Langflow's include opt-in returns its tool results as items after the message.
        events = _parse_sse(await self._stream_body(flow_events, include=["tool_call.results"]))
        tool_events = [event for event in events if event.get("output_index") == 1]
        self.assertEqual(
            [event["type"] for event in tool_events],
            [
                "response.output_item.added",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
                "response.output_item.done",
            ],
        )
        ResponseFunctionCallArgumentsDeltaEvent.model_validate(tool_events[1])
        ResponseFunctionCallArgumentsDoneEvent.model_validate(tool_events[2])
        self.assertEqual([item["type"] for item in events[-1]["response"]["output"]], ["message", "tool_call"])

    async def test_non_streaming_flow_tool_calls_stay_private_unless_included(self):
        step = SimpleNamespace(type="tool_use", name="search", tool_input={"query": "Langflow"}, output="Found", error=None)
        component_output = SimpleNamespace(
            messages=[SimpleNamespace(message="Found it")],
            results={"message": SimpleNamespace(content_blocks=[step])},
        )
        result = SimpleNamespace(outputs=[SimpleNamespace(outputs=[component_output])])
        flow = SimpleNamespace(
            id="flow-id",
            user_id="user-id",
            data={"nodes": [{"data": {"type": "ChatInput"}}, {"data": {"type": "ChatOutput"}}]},
        )
        for include, item_types in ((None, ["message"]), (["tool_call.results"], ["tool_call", "message"])):
            with (
                self.subTest(include=include),
                patch.object(openai_responses, "_store_history", AsyncMock()),
                patch.object(openai_responses, "simple_run_flow", AsyncMock(return_value=result)),
            ):
                response = await openai_responses.run_flow_for_openai_responses(
                    flow=flow,
                    request=OpenAIResponsesRequest(model="FirstFlow", input="Hello", include=include),
                    api_key_user=SimpleNamespace(id="user-id"),
                )
                self.assertEqual([item["type"] for item in response.output], item_types)

    async def test_final_text_matches_streamed_deltas(self):
        # Chat Output can republish a streamed agent answer through a Prompt under its own id.
        body = await self._stream_body(
            [
                {"event": "token", "data": {"id": "agent-message", "chunk": "The answer is X"}},
                {
                    "event": "add_message",
                    "data": {
                        "id": "chat-output",
                        "sender": "Machine",
                        "sender_name": "AI",
                        "text": "Answer: The answer is X",
                        "properties": {"state": "complete"},
                    },
                },
            ]
        )
        events = _parse_sse(body)
        streamed = "".join(event["delta"] for event in events if event["type"] == "response.output_text.delta")
        self.assertEqual(_sdk_final_response(body).output_text, streamed)
        self.assertEqual(next(event for event in events if event["type"] == "response.output_text.done")["text"], streamed)

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
        error = ResponseErrorEvent.model_validate(events[-1])
        self.assertEqual(error.message, "Workflow execution failed.")
        self.assertNotIn(str(raw_error), body)
        log_exception.assert_awaited_once_with("Error in OpenAI Responses stream generator")

    async def _stream_body(self, flow_events: list[dict] | Exception, **request_fields) -> str:
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
        request = OpenAIResponsesRequest(model="FirstFlow", input="Hello", stream=True, **request_fields)
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
