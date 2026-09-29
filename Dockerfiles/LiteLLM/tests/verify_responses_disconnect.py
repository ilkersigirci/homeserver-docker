"""Verify cancelled Responses retain partial text through native failure logging."""

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
        dynamic_async_failure_callbacks=[callback],
    )
    logger.update_environment_variables(
        litellm_params={"custom_llm_provider": "openai"},
        optional_params={},
        custom_llm_provider="openai",
    )
    text_parts = [
        (0, 0, "Partial answer "),
        (0, 0, "about Ankara"),
        (0, 1, "Another content part"),
        (1, 0, "Second message"),
    ]
    events = [
        {
            "type": "response.in_progress",
            "sequence_number": 0,
            "response": {
                "id": "resp_disconnect_check",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4o",
                "status": "in_progress",
                "output": [],
            },
        },
        *[
            {
                "type": "response.output_text.delta",
                "sequence_number": number,
                "item_id": f"msg_disconnect_check_{output_index}",
                "output_index": output_index,
                "content_index": content_index,
                "delta": text,
            }
            for number, (output_index, content_index, text) in enumerate(
                text_parts, start=1
            )
        ],
    ]
    response = httpx.Response(
        200,
        content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )
    stream = ResponsesAPIStreamingIterator(
        response=response,
        model="gpt-4o",
        responses_api_provider_config=OpenAIResponsesAPIConfig(),
        logging_obj=logger,
        custom_llm_provider="openai",
    )
    if wrapped:
        stream = await litellm.Router(model_list=[])._aresponses_streaming_iterator(
            stream, {"model": "gpt-4o"}
        )
    if terminal:
        # The provider already emitted its terminal event; its own logging task
        # owns the result even if disconnect cleanup runs before that task.
        stream.completed_response = Mock()
    request_data = {
        "model": "gpt-4o",
        "input": [{"role": "user", "content": "Tell me about Ankara"}],
        "stream": True,
        "litellm_call_id": "responses_disconnect_check",
        "litellm_logging_obj": logger,
    }
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
        for event in events[:1] if before_text else events:
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
        if not terminal and not disabled:
            writer.update_database.assert_awaited_once()
            write = writer.update_database.call_args.kwargs
            payload = get_logging_payload(
                kwargs=write["kwargs"],
                response_obj=write["completion_response"],
                start_time=write["start_time"],
                end_time=write["end_time"],
            )
    await response.aclose()
    if terminal or disabled:
        writer.update_database.assert_not_awaited()
        callback.async_log_failure_event.assert_not_awaited()
        return
    callback.async_log_failure_event.assert_awaited_once()
    assert payload["status"] == "failure", payload
    assert payload["call_type"] == "aresponses", payload
    assert payload["spend"] == 0, payload
    assert payload["completion_tokens"] == 0, payload
    metadata = json.loads(payload["metadata"])
    assert metadata["error_information"]["error_code"] == "499", metadata
    assert "Client disconnected" in metadata["error_information"]["error_message"]
    assert metadata["litellm_call_id"] == "responses_disconnect_check", metadata
    stored_response = json.loads(payload["response"])
    if before_text or not store_prompts:
        assert stored_response == {}, stored_response
    elif redact:
        callback_payload = json.dumps(
            callback.async_log_failure_event.call_args.kwargs, default=str
        )
        for _, _, text in text_parts:
            assert text not in payload["response"], payload
            assert text not in callback_payload, callback_payload
    else:
        assert stored_response["status"] == "cancelled", stored_response
        assert stored_response["usage"] is None, stored_response
        output = stored_response["output"]
        assert len(output) == 2, output
        assert output[0]["id"] == "msg_disconnect_check_0", output
        assert output[0]["status"] == "incomplete", output
        assert [part["text"] for part in output[0]["content"]] == [
            "Partial answer about Ankara",
            "Another content part",
        ], output
        assert output[1]["content"][0]["text"] == "Second message", output


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
