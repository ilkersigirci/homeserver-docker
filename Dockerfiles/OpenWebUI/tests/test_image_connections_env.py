"""IMAGE_CONNECTIONS sets the image connections from the environment."""

import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.models.config import Config
from open_webui.routers import images
from open_webui.utils.images.connections import migrate_legacy_image_config

GATEWAY = "https://gateway.example/v1"
USER = SimpleNamespace(id="user-id", role="user")
TOKEN = {"access_token": "user-token"}
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
CONNECTION = {
    "id": "gateway",
    "name": "Gateway",
    "type": "openai",
    "url": f"{GATEWAY}/",
    "config": {
        "auth_type": "system_oauth",
        "model_ids": ["gpt-image-1"],
        "access_grants": [{"principal_type": "user", "principal_id": "*", "permission": "read"}],
    },
}
# Legacy settings, which Open WebUI migrates into a connection when IMAGE_CONNECTIONS is unset.
LEGACY = {
    "image_generation.enable": True,
    "image_generation.engine": "openai",
    "image_generation.openai.api_base_url": "https://legacy.example/v1",
    "image_generation.openai.api_key": "static-key",
}


async def start(env: list | dict | str, stored: list | None = None) -> tuple[list[dict], AsyncMock]:
    """Start up with IMAGE_CONNECTIONS set to env, JSON-encoded unless a string; returns the connections and writes."""
    upsert = AsyncMock()
    with (
        patch("open_webui.config.IMAGE_CONNECTIONS", env if isinstance(env, str) else json.dumps(env)),
        patch.object(Config, "get", AsyncMock(return_value=stored)),
        patch.object(Config, "get_many", AsyncMock(return_value=LEGACY)),
        patch.object(Config, "upsert", upsert),
    ):
        return await migrate_legacy_image_config(), upsert


class FakeResponse:
    ok = True

    async def json(self, content_type=None) -> dict:
        return {"data": [{"b64_json": PNG}]}


class FakeSession:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    @contextlib.asynccontextmanager
    async def post(self, **kwargs):
        self.headers.append(kwargs["headers"])
        yield FakeResponse()


async def authorization(connection: dict, generate: bool, token: object) -> str | None:
    """The Authorization header that one image generation or edit on the connection sends."""
    session = FakeSession()
    with (
        patch.object(images, "resolve_image_model", AsyncMock(return_value=(connection, "gpt-image-1"))),
        patch.object(images, "get_session", AsyncMock(return_value=session)),
        patch.object(images, "upload_image", AsyncMock(return_value=(None, {"url": "/image"}))),
        patch("open_webui.utils.headers.get_system_oauth_token", AsyncMock(return_value=token)),
    ):
        if generate:
            await images.image_generations(SimpleNamespace(), images.CreateImageForm(prompt="A cat"), user=USER)
        else:
            form = images.EditImageForm(prompt="A cat", image=f"data:image/png;base64,{PNG}")
            await images.image_edits(SimpleNamespace(), form, user=USER)
    [headers] = session.headers
    return headers.get("Authorization")


class ImageConnectionsEnvTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_environment_connections_replace_the_legacy_settings(self) -> None:
        connections, upsert = await start([CONNECTION])
        [connection] = connections
        self.assertEqual(
            (connection["id"], connection["url"], connection["config"]["auth_type"]),
            ("gateway", GATEWAY, "system_oauth"),
        )
        upsert.assert_awaited_once_with({"images.connections": connections})

    async def test_stored_connections_win(self) -> None:
        stored = [{"id": "stored"}]
        connections, upsert = await start([CONNECTION], stored)
        self.assertEqual(connections, stored)
        upsert.assert_not_awaited()

    async def test_an_invalid_value_stops_startup(self) -> None:
        for env in (
            "[{",
            {"connections": [CONNECTION]},
            ["gateway"],
            [{**CONNECTION, "config": {"auth_type": "unknown"}}],
            [CONNECTION, CONNECTION],
        ):
            with self.subTest(env=env), self.assertRaises(ValueError):
                await start(env)

    async def test_without_it_open_webui_migrates_the_legacy_settings(self) -> None:
        [connection], _ = await start("")
        self.assertEqual(
            (connection["url"], connection["key"], connection["config"]["auth_type"]),
            ("https://legacy.example/v1", "static-key", "bearer"),
        )

    async def test_a_system_oauth_connection_sends_the_user_token_and_never_the_key(self) -> None:
        [connection], _ = await start([{**CONNECTION, "key": "static-key"}])
        for generate in (True, False):
            with self.subTest(generate=generate):
                self.assertEqual(await authorization(connection, generate, TOKEN), "Bearer user-token")
                self.assertIsNone(await authorization(connection, generate, None))


if __name__ == "__main__":
    unittest.main()
