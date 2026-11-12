"""A connection's responses_model_ids sends its matching models to the Responses API."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.routers import openai

GATEWAY = "http://gateway/v1"
USER = SimpleNamespace(id="user-id", name="User", email="user@example.com", role="user")
RESPONSES_RESULT = {
    "status": "completed",
    "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hi"}]}],
}
CHAT_RESULT = {"choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}}]}


async def chat(config: dict, model_id: str, workspace_base_model_id: str | None = None) -> tuple[str, dict, dict]:
    """Send one non-streaming chat; return the provider URL and body, and Open WebUI's result."""

    async def provider(*, url: str, **_: object) -> MagicMock:
        response = MagicMock(status=200, headers={"Content-Type": "application/json"})
        response.json = AsyncMock(return_value=RESPONSES_RESULT if url.endswith("/responses") else CHAT_RESULT)
        return response

    session = SimpleNamespace(request=AsyncMock(side_effect=provider))
    model_info = (
        SimpleNamespace(base_model_id=workspace_base_model_id, params=SimpleNamespace(model_dump=dict))
        if workspace_base_model_id
        else None
    )
    listed_id = workspace_base_model_id or model_id
    request = SimpleNamespace(
        state=SimpleNamespace(), app=SimpleNamespace(state=SimpleNamespace(OPENAI_MODELS={listed_id: {"urlIdx": 0}}))
    )
    form_data = {
        "model": model_id,
        "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hello"}],
    }
    with (
        patch.object(openai.Config, "get", AsyncMock(return_value=True)),
        patch.object(openai.Models, "get_model_by_id", AsyncMock(return_value=model_info)),
        patch.object(openai, "check_model_access", AsyncMock()),
        patch.object(openai, "get_openai_connection", AsyncMock(return_value=(GATEWAY, "key", config))),
        patch.object(openai, "get_headers_and_cookies", AsyncMock(return_value=({}, {}))),
        patch.object(openai, "get_session", AsyncMock(return_value=session)),
        patch.object(openai, "cleanup_response", AsyncMock()),
    ):
        result = await openai.generate_chat_completion(request, form_data, user=USER)
    sent = session.request.call_args.kwargs
    return sent["url"], json.loads(sent["data"]), result


class ResponsesModelIdsTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_matching_models_use_the_responses_api(self) -> None:
        config = {"responses_model_ids": ["langflow/*"]}

        url, body, result = await chat(config, "langflow/flow")
        self.assertEqual(url, f"{GATEWAY}/responses")
        self.assertEqual(body["instructions"], "Be brief.")
        self.assertEqual(
            body["input"], [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]}]
        )
        self.assertNotIn("messages", body)
        self.assertEqual(result["choices"][0]["message"]["content"], "Hi")

        url, body, result = await chat(config, "qwen/qwen3")
        self.assertEqual(url, f"{GATEWAY}/chat/completions")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "Hello"})
        self.assertEqual(result["choices"][0]["message"]["content"], "Hi")

    async def test_patterns_match_provider_ids_before_prefix_id(self) -> None:
        url, body, _ = await chat({"responses_model_ids": ["langflow/*"], "prefix_id": "gw"}, "gw.langflow/flow")

        self.assertEqual(url, f"{GATEWAY}/responses")
        self.assertEqual(body["model"], "langflow/flow")

    async def test_workspace_models_match_by_base_model(self) -> None:
        url, body, _ = await chat({"responses_model_ids": ["langflow/*"]}, "my-assistant", "langflow/flow")

        self.assertEqual(url, f"{GATEWAY}/responses")
        self.assertEqual(body["model"], "langflow/flow")

    async def test_a_responses_connection_still_sends_every_model_to_the_responses_api(self) -> None:
        url, _, _ = await chat({"api_type": "responses", "responses_model_ids": ["langflow/*"]}, "qwen/qwen3")

        self.assertEqual(url, f"{GATEWAY}/responses")

    async def test_values_other_than_a_list_of_patterns_match_no_model(self) -> None:
        for value in (None, "*", {"*": True}, [None, 3]):
            with self.subTest(value=value):
                url, _, _ = await chat({"responses_model_ids": value}, "qwen/qwen3")

                self.assertEqual(url, f"{GATEWAY}/chat/completions")


if __name__ == "__main__":
    unittest.main()
