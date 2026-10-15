"""Speech and images authenticate like the OpenAI connection with the same base URL."""

import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
from fastapi import HTTPException
from open_webui.routers import audio, images
from open_webui.routers.audio import realtime

GATEWAY = "https://gateway.example/v1"
# An admin, so the realtime call needs no separate call permission.
USER = SimpleNamespace(id="user-id", role="admin")
TOKEN = {"access_token": "user-token"}
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
FLOWS = (
    "speech-to-text",
    "text-to-speech",
    "realtime text-to-speech",
    "realtime voice call",
    "image generation",
    "image edit",
)


class FakeResponse:
    status = 200
    headers = {"Content-Type": "audio/mpeg"}

    def raise_for_status(self) -> None:
        return None

    async def json(self, content_type=None) -> dict:
        return {"text": "Hello", "data": [{"b64_json": PNG}]}

    async def read(self) -> bytes:
        return b"audio"


class FakeCall:
    """A session.post() result that speech awaits and images enter."""

    def __await__(self):
        return asyncio.sleep(0, result=FakeResponse()).__await__()

    async def __aenter__(self) -> FakeResponse:
        return FakeResponse()

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    def post(self, **kwargs) -> FakeCall:
        self.headers.append(kwargs["headers"])
        return FakeCall()

    async def ws_connect(self, url: str, **kwargs) -> None:
        """Record the Realtime credential, then refuse the connection."""
        self.headers.append(kwargs["headers"])
        raise aiohttp.ClientError


class FakeWebSocket:
    """A browser's realtime call socket that authenticates and then waits."""

    def __init__(self) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(redis=None, MODELS={"chat-model": {"id": "chat-model"}}))
        self.cookies: dict[str, str] = {}

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        return json.dumps({"type": "auth", "token": "session-token", "model_id": "chat-model"})

    async def send_json(self, message: object) -> None:
        return None

    async def close(self) -> None:
        return None


async def send(flow: str, user: object, feature_url: str, workdir: Path) -> None:
    request = SimpleNamespace()
    if flow == "speech-to-text":
        recording = workdir / "recording.wav"
        recording.write_bytes(b"audio")
        await audio._transcribe_openai(request, str(recording), recording.name, [None], str(workdir), "id", user)
    elif flow == "text-to-speech":
        await audio._tts_openai(request, {"input": "Hello"}, workdir / "speech.mp3", workdir / "speech.json", user)
    elif flow == "realtime text-to-speech":
        payload = {
            "input": "Hello",
            "model": "gpt-realtime",
            "voice": "marin",
            "instructions": "Read it.",
            "api_base_url": feature_url,
        }
        with contextlib.suppress(HTTPException):
            await audio._tts_openai_realtime(request, payload, workdir / "speech.wav", workdir / "speech.json", user)
    elif flow == "realtime voice call":
        with patch.object(realtime, "get_verified_user_by_token", AsyncMock(return_value=user)):
            await realtime.realtime_call(FakeWebSocket())
    elif flow == "image generation":
        await images.image_generations(request, images.CreateImageForm(prompt="A cat"), user=user)
    else:
        form = images.EditImageForm(prompt="A cat", image=f"data:image/png;base64,{PNG}")
        await images.image_edits(request, form, user=user)


async def request_headers(
    flow: str,
    auth_type: str,
    feature_url: str,
    user: object,
    token: object,
    *,
    realtime_provider: str = "openai",
    realtime_auth_type: str = "api_key",
) -> dict[str, str]:
    """The headers one request sends, or an empty dict when none is sent."""
    settings = {
        "audio.stt.openai.api_base_url": feature_url,
        "audio.stt.openai.api_key": "static-key",
        "audio.stt.openai.api_request_format": "multipart",
        "audio.stt.model": "transcribe",
        "audio.tts.openai.api_base_url": feature_url,
        "audio.tts.openai.api_key": "static-key",
        "audio.tts.model": "speech",
        "audio.tts.voice": "alloy",
        "audio.realtime.enabled": True,
        "audio.realtime.provider": realtime_provider,
        "audio.realtime.auth_type": realtime_auth_type,
        "audio.realtime.openai.api_base_url": feature_url,
        "audio.realtime.openai.api_key": "static-key",
        "audio.realtime.model": "gpt-realtime",
        "audio.realtime.voice": "marin",
        "audio.realtime.transcription_model": "transcribe",
        "user.permissions": {},
    }
    image_config = SimpleNamespace(
        IMAGE_GENERATION_ENGINE="openai",
        IMAGES_OPENAI_API_BASE_URL=feature_url,
        IMAGES_OPENAI_API_KEY="static-key",
        IMAGES_OPENAI_API_VERSION="",
        IMAGES_OPENAI_API_PARAMS=None,
        IMAGE_GENERATION_MODEL="gpt-image-1",
        IMAGE_SIZE="1024x1024",
        IMAGE_EDIT_ENGINE="openai",
        IMAGES_EDIT_OPENAI_API_BASE_URL=feature_url,
        IMAGES_EDIT_OPENAI_API_KEY="static-key",
        IMAGES_EDIT_OPENAI_API_VERSION="",
        IMAGE_EDIT_MODEL="gpt-image-1",
        IMAGE_EDIT_SIZE="1024x1024",
    )
    connections = (True, [GATEWAY], [""], {"0": {"auth_type": auth_type}})
    session = FakeSession()

    async def setting(key: str, default: object = None) -> object:
        return settings.get(key, default)

    async def many(*keys: str) -> dict[str, object]:
        return {key: settings.get(key) for key in keys}

    with (
        tempfile.TemporaryDirectory() as workdir,
        patch("open_webui.routers.openai.get_openai_runtime_config", AsyncMock(return_value=connections)),
        patch("open_webui.utils.middleware.get_system_oauth_token", AsyncMock(return_value=token)),
        patch.object(audio.Config, "get", setting),
        patch.object(audio.Config, "get_many", many),
        patch.object(audio, "get_session", AsyncMock(return_value=session)),
        patch.object(realtime, "get_session", AsyncMock(return_value=session)),
        patch.object(realtime.Models, "get_model_by_id", AsyncMock(return_value=None)),
        patch.object(images, "get_session", AsyncMock(return_value=session)),
        patch.object(images, "get_image_config", AsyncMock(return_value=image_config)),
        patch.object(images, "get_image_model", AsyncMock(return_value="gpt-image-1")),
        patch.object(images, "upload_image", AsyncMock(return_value=(None, {"url": "/image"}))),
    ):
        await send(flow, user, feature_url, Path(workdir))
    assert len(session.headers) <= 1, session.headers
    return session.headers[0] if session.headers else {}


async def authorization(flow: str, auth_type: str, feature_url: str, user: object, token: object) -> str | None:
    """The Authorization header one request sends, or None when none is sent."""
    return (await request_headers(flow, auth_type, feature_url, user, token)).get("Authorization")


class SpeechImagesSystemOAuthTest(unittest.IsolatedAsyncioTestCase):
    async def test_azure_realtime_keeps_its_provider_credentials(self) -> None:
        for auth_type, expected in (
            ("api_key", {"api-key": "static-key"}),
            ("microsoft_entra_id", {"Authorization": "Bearer entra-token"}),
        ):
            with (
                self.subTest(auth_type=auth_type),
                patch.object(realtime, "get_microsoft_entra_id_access_token", return_value="entra-token"),
            ):
                self.assertEqual(
                    await request_headers(
                        "realtime voice call", "system_oauth", GATEWAY, USER, TOKEN,
                        realtime_provider="azure", realtime_auth_type=auth_type,
                    ),
                    expected,
                )

    async def test_a_system_oauth_connection_sends_the_user_token_and_never_the_key(self) -> None:
        for flow in FLOWS:
            with self.subTest(flow=flow):
                self.assertEqual(
                    await authorization(flow, "system_oauth", f"{GATEWAY}/", USER, TOKEN), "Bearer user-token"
                )
                # Without a token, a request carries none, or is never sent.
                self.assertIn(await authorization(flow, "system_oauth", GATEWAY, USER, None), ("Bearer ", None))
                self.assertIn(await authorization(flow, "system_oauth", GATEWAY, None, TOKEN), ("Bearer ", None))

    async def test_other_connections_keep_the_configured_key(self) -> None:
        for flow in FLOWS:
            with self.subTest(flow=flow):
                self.assertEqual(await authorization(flow, "bearer", GATEWAY, USER, TOKEN), "Bearer static-key")
                self.assertEqual(
                    await authorization(flow, "system_oauth", "https://other.example/v1", USER, TOKEN),
                    "Bearer static-key",
                )


if __name__ == "__main__":
    unittest.main()
