"""A manifold Pipe's pipes() receives the signed-in user's OAuth token."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui import functions

USER = SimpleNamespace(id="user-id")
TOKEN = {"access_token": "user-token"}


async def list_models(module: object, user: object) -> list[str]:
    pipe = SimpleNamespace(id="manifold", type="pipe", name="Manifold", created_at=0)
    with (
        patch.object(functions.Functions, "get_functions_by_type", AsyncMock(return_value=[pipe])),
        patch.object(functions, "get_function_module_by_id", AsyncMock(return_value=module)),
        patch("open_webui.utils.middleware.get_system_oauth_token", AsyncMock(return_value=TOKEN)),
    ):
        return [model["id"] for model in await functions.get_function_models(SimpleNamespace(), user)]


class PipesUserContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_pipes_receive_the_token_they_declare(self) -> None:
        received = []

        async def pipes(__oauth_token__=None):
            received.append(__oauth_token__)
            return [{"id": "model", "name": "Model"}]

        for user, token in ((USER, TOKEN), (None, None)):
            self.assertEqual(await list_models(SimpleNamespace(pipes=pipes), user), ["manifold.model"])
            self.assertEqual(received.pop(), token)

    async def test_pipes_without_the_parameter_are_called_as_before(self) -> None:
        def pipes():
            return [{"id": "model", "name": "Model"}]

        self.assertEqual(await list_models(SimpleNamespace(pipes=pipes), USER), ["manifold.model"])


if __name__ == "__main__":
    unittest.main()
