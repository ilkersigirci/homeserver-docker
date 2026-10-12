"""Verify realtime transcripts start a proxy response only when a transcript guardrail owns the turn."""

import asyncio
import json
from collections.abc import Sequence
from typing import Final
from unittest.mock import AsyncMock, MagicMock

import litellm
from websockets.exceptions import ConnectionClosed

from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.litellm_core_utils.realtime_streaming import RealTimeStreaming
from litellm.llms.base_llm.realtime.transformation import BaseRealtimeConfig
from litellm.types.guardrails import GuardrailEventHooks
from litellm.types.realtime import RealtimeResponseTransformInput, RealtimeResponseTypedDict


class PassthroughRealtimeConfig(BaseRealtimeConfig):
    def validate_environment(self, headers: dict, model: str, api_key: str | None = None) -> dict:
        return headers

    def get_complete_url(self, api_base: str | None, model: str, api_key: str | None = None) -> str:
        return api_base or ""

    def transform_realtime_request(
        self, message: str, model: str, session_configuration_request: str | None = None
    ) -> Sequence[str | bytes]:
        return (message,)

    def transform_realtime_response(
        self,
        message: str | bytes,
        model: str,
        logging_obj: Logging,
        realtime_response_transform_input: RealtimeResponseTransformInput,
    ) -> RealtimeResponseTypedDict:
        return {
            "response": [json.loads(message)],
            "current_output_item_id": realtime_response_transform_input["current_output_item_id"],
            "current_response_id": realtime_response_transform_input["current_response_id"],
            "current_delta_chunks": realtime_response_transform_input["current_delta_chunks"],
            "current_conversation_id": realtime_response_transform_input["current_conversation_id"],
            "current_item_chunks": realtime_response_transform_input["current_item_chunks"],
            "current_delta_type": realtime_response_transform_input["current_delta_type"],
            "session_configuration_request": realtime_response_transform_input["session_configuration_request"],
        }


class TranscriptGuardrail(CustomGuardrail):
    async def apply_guardrail(self, inputs, request_data, input_type, logging_obj=None):
        return inputs


async def response_creates(event_hook: GuardrailEventHooks | None, through_provider_config: bool) -> int:
    litellm.callbacks = (
        [TranscriptGuardrail(guardrail_name="transcript-check", event_hook=event_hook, default_on=True)]
        if event_hook
        else []
    )
    completed: Final = json.dumps(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_1",
            "content_index": 0,
            "transcript": "What are the opening hours tomorrow?",
        }
    ).encode()
    backend_ws: Final = MagicMock(
        recv=AsyncMock(side_effect=[completed, ConnectionClosed(None, None)]),
        send=AsyncMock(),
    )
    client_ws: Final = MagicMock(send_text=AsyncMock())
    streaming: Final = RealTimeStreaming(
        client_ws,
        backend_ws,
        MagicMock(async_success_handler=AsyncMock()),
        provider_config=PassthroughRealtimeConfig() if through_provider_config else None,
    )
    await streaming.backend_to_client_send_messages()

    assert [json.loads(call.args[0]) for call in client_ws.send_text.await_args_list] == [json.loads(completed)]
    sent: Final = [json.loads(call.args[0]) for call in backend_ws.send.await_args_list]
    assert all(event == {"type": "response.create"} for event in sent), sent
    return len(sent)


async def main() -> None:
    original_callbacks: Final = litellm.callbacks
    try:
        for through_provider_config in (False, True):
            # A client that set create_response=false requests its own response.
            assert await response_creates(None, through_provider_config) == 0
            assert await response_creates(GuardrailEventHooks.pre_call, through_provider_config) == 0
            # The proxy disabled VAD auto-response for this guardrail, so it starts the turn.
            assert (
                await response_creates(GuardrailEventHooks.realtime_input_transcription, through_provider_config) == 1
            )
    finally:
        litellm.callbacks = original_callbacks


if __name__ == "__main__":
    asyncio.run(main())
