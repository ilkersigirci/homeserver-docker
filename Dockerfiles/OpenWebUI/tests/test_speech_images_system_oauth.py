"""Speech and images authenticate like the OpenAI connection with the same base URL."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.routers import audio, images

GATEWAY = "https://gateway.example/v1"
USER = SimpleNamespace(id="user-id")
TOKEN = {"access_token": "user-token"}
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
FLOWS = ("speech-to-text", "text-to-speech", "image generation", "image edit")


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
        self.authorization: list[str] = []

    def post(self, **kwargs) -> FakeCall:
        self.authorization.append(kwargs["headers"]["Authorization"])
        return FakeCall()


async def send(flow: str, user: object, workdir: Path) -> None:
    request = SimpleNamespace()
    if flow == "speech-to-text":
        recording = workdir / "recording.wav"
        recording.write_bytes(b"audio")
        await audio._transcribe_openai(request, str(recording), recording.name, [None], str(workdir), "id", user)
    elif flow == "text-to-speech":
        await audio._tts_openai(request, {"input": "Hello"}, workdir / "speech.mp3", workdir / "speech.json", user)
    elif flow == "image generation":
        await images.image_generations(request, images.CreateImageForm(prompt="A cat"), user=user)
    else:
        form = images.EditImageForm(prompt="A cat", image=f"data:image/png;base64,{PNG}")
        await images.image_edits(request, form, user=user)


async def authorization(flow: str, auth_type: str, feature_url: str, user: object, token: object) -> str:
    """The Authorization header one request sends, with the chat connection at GATEWAY."""
    settings = {
        "audio.stt.openai.api_base_url": feature_url,
        "audio.stt.openai.api_key": "static-key",
        "audio.stt.openai.api_request_format": "multipart",
        "audio.stt.model": "transcribe",
        "audio.tts.openai.api_base_url": feature_url,
        "audio.tts.openai.api_key": "static-key",
        "audio.tts.model": "speech",
        "audio.tts.voice": "alloy",
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

    with (
        tempfile.TemporaryDirectory() as workdir,
        patch("open_webui.routers.openai.get_openai_runtime_config", AsyncMock(return_value=connections)),
        patch("open_webui.utils.middleware.get_system_oauth_token", AsyncMock(return_value=token)),
        patch.object(audio.Config, "get", setting),
        patch.object(audio, "get_session", AsyncMock(return_value=session)),
        patch.object(images, "get_session", AsyncMock(return_value=session)),
        patch.object(images, "get_image_config", AsyncMock(return_value=image_config)),
        patch.object(images, "get_image_model", AsyncMock(return_value="gpt-image-1")),
        patch.object(images, "upload_image", AsyncMock(return_value=(None, {"url": "/image"}))),
    ):
        await send(flow, user, Path(workdir))
    (header,) = session.authorization
    return header


class SpeechImagesSystemOAuthTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_system_oauth_connection_sends_the_user_token_and_never_the_key(self) -> None:
        for flow in FLOWS:
            with self.subTest(flow=flow):
                self.assertEqual(
                    await authorization(flow, "system_oauth", f"{GATEWAY}/", USER, TOKEN), "Bearer user-token"
                )
                self.assertEqual(await authorization(flow, "system_oauth", GATEWAY, USER, None), "Bearer ")
                self.assertEqual(await authorization(flow, "system_oauth", GATEWAY, None, TOKEN), "Bearer ")

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
