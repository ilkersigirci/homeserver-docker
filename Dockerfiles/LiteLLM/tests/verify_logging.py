"""Verify Responses parsing, success callbacks, and database-ready spend-log payloads."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from litellm.integrations.custom_logger import CustomLogger
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig
from litellm.proxy.spend_tracking.spend_tracking_utils import get_logging_payload
from litellm.types.llms.openai import ResponsesAPIResponse


async def verify_logging(
    status: str | None, shape: str, usage: bool, is_async: bool
) -> None:
    response = {
        "id": "resp_logging_check",
        # LGOS emits fractional timestamps; LiteLLM expects an int and falls back
        # to a dictionary response when parsing these streaming events.
        "created_at": 1.5 if shape == "dict" else 1,
        "model": "gpt-4o",
        "object": "response",
        "status": status or "completed",
        "output": [
            {
                "id": "msg_logging_check",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "Hello!", "annotations": []}
                ],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 2},
            "output_tokens_details": {"reasoning_tokens": 1},
        }
        if usage
        else None,
    }
    if shape == "typed":
        response = ResponsesAPIResponse(**response)
    elif shape == "constructed":
        response = ResponsesAPIResponse.model_construct(**response)
    callback = CustomLogger()
    callback.log_success_event = Mock()
    callback.async_log_success_event = AsyncMock()
    now = datetime.now()
    logger = Logging(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello"}],
        stream=status is not None,
        call_type="aresponses" if is_async else "responses",
        start_time=now,
        litellm_call_id="logging_check",
        function_id="logging_check",
        dynamic_success_callbacks=[callback],
        dynamic_async_success_callbacks=[callback],
    )
    logger.update_environment_variables(
        litellm_params={"custom_llm_provider": "openai"},
        optional_params={},
        custom_llm_provider="openai",
    )
    result = response
    if status is not None:
        event_type = f"response.{status}"
        event = {"type": event_type, "sequence_number": 0, "response": response}
        result = OpenAIResponsesAPIConfig().transform_streaming_response(
            model="gpt-4o", parsed_chunk=event, logging_obj=logger
        )
    if is_async:
        await logger.async_success_handler(result=result, start_time=now, end_time=now)
        callback.async_log_success_event.assert_awaited_once()
        logged = callback.async_log_success_event.call_args.kwargs
    else:
        logger.success_handler(result=result, start_time=now, end_time=now)
        callback.log_success_event.assert_called_once()
        logged = callback.log_success_event.call_args.kwargs

    payload = get_logging_payload(**logged)
    assert payload["status"] == "success", payload
    assert payload["model"] == "gpt-4o", payload
    assert payload["prompt_tokens"] == (10 if usage else 0), payload
    assert payload["completion_tokens"] == (5 if usage else 0), payload
    assert payload["total_tokens"] == (15 if usage else 0), payload
    stored_response = json.loads(payload["response"])
    assert stored_response["id"] == "resp_logging_check", stored_response
    assert stored_response["output"][0]["content"][0]["text"] == "Hello!"
    if usage:
        assert payload["spend"] > 0, payload
        stored_usage = stored_response["usage"]
        input_details = stored_usage.get(
            "prompt_tokens_details", stored_usage.get("input_tokens_details")
        )
        output_details = stored_usage.get(
            "completion_tokens_details", stored_usage.get("output_tokens_details")
        )
        assert input_details["cached_tokens"] == 2
        assert output_details["reasoning_tokens"] == 1


async def main() -> None:
    with patch.dict("os.environ", STORE_PROMPTS_IN_SPEND_LOGS="true"):
        for status in ("completed", "incomplete", "failed", None):
            for shape in ("dict", "constructed", "typed"):
                for usage in (True, False):
                    for is_async in (True, False):
                        await verify_logging(status, shape, usage, is_async)
    print("Responses success logging checks passed")


if __name__ == "__main__":
    asyncio.run(main())
