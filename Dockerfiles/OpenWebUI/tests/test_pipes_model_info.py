"""A manifold Pipe's pipes() entries carry their model info."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui import functions

INFO = {"meta": {"description": "Listed by the Pipe", "toolIds": ["server:mcp:tools"]}}


async def list_models(entries: list[dict]) -> list[dict]:
    pipe = SimpleNamespace(id="manifold", type="pipe", name="Manifold", created_at=0)
    module = SimpleNamespace(pipes=lambda: entries)
    with (
        patch.object(functions.Functions, "get_functions_by_type", AsyncMock(return_value=[pipe])),
        patch.object(functions, "get_function_module_by_id", AsyncMock(return_value=module)),
    ):
        return await functions.get_function_models(SimpleNamespace())


class PipesModelInfoTest(unittest.IsolatedAsyncioTestCase):
    async def test_entries_keep_the_info_they_list(self) -> None:
        models = await list_models(
            [{"id": "described", "name": "Described", "info": INFO}, {"id": "plain", "name": "Plain"}]
        )

        self.assertEqual(
            {model["id"]: model.get("info") for model in models},
            {"manifold.described": INFO, "manifold.plain": None},
        )
        self.assertNotIn("info", models[1])


if __name__ == "__main__":
    unittest.main()
