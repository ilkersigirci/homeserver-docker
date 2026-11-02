"""Verify cancelled Responses reach native logging once, before and after output."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import anyio
import httpx
import litellm
from litellm.integrations.custom_logger import CustomLogger
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig
from litellm.proxy import proxy_server
from litellm.proxy._types import UserAPIKeyAuth
from litellm.proxy.common_request_processing import ProxyBaseLLMRequestProcessing
from litellm.proxy.common_utils.user_api_key_cache import UserApiKeyCache
from litellm.proxy.hooks.proxy_track_cost_callback import _ProxyDBLogger
from litellm.proxy.spend_tracking.spend_tracking_utils import get_logging_payload
from litellm.proxy.utils import ProxyLogging
from litellm.responses.streaming_iterator import ResponsesAPIStreamingIterator


async def verify_disconnect(
    wrapped: bool,
    terminal: bool = False,
    disabled: bool = False,
    store_prompts: bool = True,
    redact: bool = False,
    before_text: bool = False,
) -> None:
    callback = CustomLogger()
    callback.async_log_success_event = AsyncMock()
    callback.async_log_failure_event = AsyncMock()
    writer = Mock(update_database=AsyncMock())
    db_callback = _ProxyDBLogger(spend_writer=lambda: writer)
    now = datetime.now()
    logger = Logging(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Tell me about Ankara"}],
        stream=True,
        call_type="aresponses",
        start_time=now,
        litellm_call_id="responses_disconnect_check",
        function_id="responses_disconnect_check",
        dynamic_async_success_callbacks=[callback],
        dynamic_async_failure_callbacks=[callback],
    )
    logger.update_environment_variables(
        litellm_params={"custom_llm_provider": "openai"},
        optional_params={},
        custom_llm_provider="openai",
    )
    text_parts = ["Partial answer ", "about Ankara"]
    provider_response = {
        "id": "resp_disconnect_check",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o",
        "status": "in_progress",
        "output": [],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }
    # Reasoning summaries are not output, so partial billing cannot count them.
    before_output = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": provider_response,
        },
        {
            "type": "response.in_progress",
            "sequence_number": 1,
            "response": provider_response,
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "sequence_number": 2,
            "item_id": "rs_disconnect_check",
            "output_index": 0,
            "summary_index": 0,
            "delta": "Thinking",
        },
    ]
    events = [
        *before_output,
        *[
            {
                "type": "response.output_text.delta",
                "sequence_number": number,
                "item_id": "msg_disconnect_check",
                "output_index": 1,
                "content_index": 0,
                "delta": text,
            }
            for number, text in enumerate(text_parts, start=len(before_output))
        ],
    ]
    response = httpx.Response(
        200,
        content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )
    request_data = {
        "model": "gpt-4o",
        "input": [{"role": "user", "content": "Tell me about Ankara"}],
        "stream": True,
        "litellm_call_id": "responses_disconnect_check",
        "litellm_logging_obj": logger,
    }
    stream = ResponsesAPIStreamingIterator(
        response=response,
        model="gpt-4o",
        responses_api_provider_config=OpenAIResponsesAPIConfig(),
        logging_obj=logger,
        request_data=request_data,
        custom_llm_provider="openai",
    )
    if terminal:
        # The provider already emitted its terminal event; its own logging task
        # owns the result even if disconnect cleanup runs before that task.
        stream.completed_response = Mock()
    if wrapped:
        source = stream
        stream = await litellm.Router(model_list=[])._aresponses_streaming_iterator(
            source, {"model": "gpt-4o"}
        )
        # The router wrapper sees the terminal event on the chunks it forwards.
        stream.completed_response = source.completed_response
    proxy = ProxyLogging(user_api_key_cache=UserApiKeyCache())
    auth = UserAPIKeyAuth(request_route="/v1/responses")
    with (
        patch.object(litellm, "callbacks", [db_callback]),
        patch.object(litellm, "disable_streaming_logging", disabled),
        patch.object(litellm, "turn_off_message_logging", redact),
        patch.object(proxy_server, "proxy_logging_obj", proxy),
        patch.dict("os.environ", STORE_PROMPTS_IN_SPEND_LOGS=str(store_prompts)),
    ):
        generator = proxy_server.async_data_generator(
            response=stream,
            user_api_key_dict=auth,
            request_data=request_data,
        )
        for event in before_output if before_text else events:
            delivered = await anext(generator)
            assert event["type"] in delivered
        # Cleanup must finish under cancellation, and repeated cleanup must not
        # produce duplicate callbacks or database writes.
        with anyio.CancelScope() as scope:
            scope.cancel()
            await generator.aclose()
            await ProxyBaseLLMRequestProcessing._finalize_streaming_generator_cleanup(
                request=None,
                request_data=request_data,
                response=stream,
                client_disconnected=True,
                user_api_key_dict=auth,
                proxy_logging_obj=proxy,
            )
        # Success callbacks run on a logging task.
        await asyncio.sleep(1)
        if terminal or disabled:
            payload = None
        elif before_text:
            writer.update_database.assert_awaited_once()
            write = writer.update_database.call_args.kwargs
            payload = get_logging_payload(
                kwargs=write["kwargs"],
                response_obj=write["completion_response"],
                start_time=write["start_time"],
                end_time=write["end_time"],
            )
        else:
            callback.async_log_success_event.assert_awaited_once()
            success = callback.async_log_success_event.call_args.kwargs
            payload = get_logging_payload(
                kwargs=success["kwargs"],
                response_obj=success["response_obj"],
                start_time=success["start_time"],
                end_time=success["end_time"],
            )
    await response.aclose()
    if terminal or disabled:
        writer.update_database.assert_not_awaited()
        callback.async_log_success_event.assert_not_awaited()
        callback.async_log_failure_event.assert_not_awaited()
        return
    metadata = json.loads(payload["metadata"])
    assert metadata["error_information"]["error_code"] == "499", metadata
    assert "Client disconnected" in metadata["error_information"]["error_message"]
    assert metadata["litellm_call_id"] == "responses_disconnect_check", metadata
    assert payload["call_type"] == "aresponses", payload
    stored_response = json.loads(payload["response"])
    if before_text:
        callback.async_log_failure_event.assert_awaited_once()
        callback.async_log_success_event.assert_not_awaited()
        assert payload["status"] == "failure", payload
        assert payload["spend"] == 0, payload
        assert payload["completion_tokens"] == 0, payload
        assert stored_response == {}, stored_response
        return
    # Upstream's partial billing owns a stream that delivered output.
    writer.update_database.assert_not_awaited()
    callback.async_log_failure_event.assert_not_awaited()
    assert payload["status"] == "success", payload
    assert payload["spend"] > 0, payload
    assert payload["completion_tokens"] > 0, payload
    if not store_prompts:
        assert stored_response == {}, stored_response
    elif redact:
        for text in text_parts:
            assert text not in payload["response"], payload
    else:
        assert stored_response["status"] == "incomplete", stored_response
        output = stored_response["output"]
        assert len(output) == 1, output
        assert output[0]["status"] == "incomplete", output
        assert output[0]["content"][0]["text"] == "".join(text_parts), output


async def main() -> None:
    for wrapped in (False, True):
        for terminal, disabled in ((False, False), (True, False), (False, True)):
            await verify_disconnect(wrapped, terminal, disabled)
        await verify_disconnect(wrapped, store_prompts=False)
        await verify_disconnect(wrapped, redact=True)
        await verify_disconnect(wrapped, before_text=True)
    print("Responses disconnect logging checks passed")


if __name__ == "__main__":
    asyncio.run(main())
