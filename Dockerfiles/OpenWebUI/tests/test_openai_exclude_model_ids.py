"""A connection's exclude_model_ids leaves its matching models out of the list."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.routers import openai

GATEWAY = "http://gateway/v1"
OTHER = "http://other/v1"


async def listed_ids(configs: dict) -> list[list[str]]:
    """List each connection's model IDs; the providers answer in both shapes."""
    upstream = {
        GATEWAY: {"data": [{"id": "acme/graph"}, {"id": "openai/gpt"}, {"id": "acme-docs/search"}]},
        OTHER: [{"id": "acme/graph"}, {"id": "other/model"}],
    }
    runtime_config = (True, [GATEWAY, OTHER], ["key", "key"], configs)
    with (
        patch.object(openai, "get_openai_runtime_config", AsyncMock(return_value=runtime_config)),
        patch.object(openai, "get_models_request", AsyncMock(side_effect=lambda _, url, *__, **___: upstream[url])),
    ):
        responses = await openai.get_all_models_responses(SimpleNamespace(), user=None)
    return [[model["id"] for model in (r if isinstance(r, list) else r["data"])] for r in responses]


class ExcludeModelIdsTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_connection_leaves_out_only_its_matching_models(self) -> None:
        ids = await listed_ids({"0": {"exclude_model_ids": ["acme/*"]}, "1": {"exclude_model_ids": ["other/*"]}})

        self.assertEqual(ids, [["openai/gpt", "acme-docs/search"], ["acme/graph"]])

    async def test_patterns_match_provider_ids_before_prefix_id(self) -> None:
        ids = await listed_ids({"0": {"exclude_model_ids": ["acme/*"], "prefix_id": "gw"}, "1": {}})

        self.assertEqual(ids, [["gw.openai/gpt", "gw.acme-docs/search"], ["acme/graph", "other/model"]])


if __name__ == "__main__":
    unittest.main()
