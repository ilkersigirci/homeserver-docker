import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Request
from litellm.proxy._types import LiteLLMRoutes, ProxyException, UserAPIKeyAuth
from litellm.proxy.auth.route_checks import RouteChecks

ISSUER = "https://pocketid.example.com"
AUDIENCE = "https://llm.example.com"

os.environ.update(
    {
        "POCKETID_ISSUER": ISSUER,
        "POCKETID_JWKS_URL": f"{ISSUER}/.well-known/jwks.json",
        "POCKETID_USERINFO_URL": f"{ISSUER}/api/oidc/userinfo",
        "LITELLM_OIDC_AUDIENCE": AUDIENCE,
        "LITELLM_OIDC_REQUIRED_SCOPE": "llm:invoke",
    }
)

import pocketid_auth


def _request(method: str = "GET", path: str = "/v1/models") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "http",
            "server": ("litellm-sso", 4000),
            "client": ("127.0.0.1", 12345),
            "path": path,
            "query_string": b"",
            "headers": [],
        }
    )


class PocketIDAuthTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        cls.public_key = cls.private_key.public_key()

    def _token(
        self,
        *,
        audience: str = AUDIENCE,
        scopes: list[str] | None = None,
        subject: str = "pocket-id-user-id",
        issued_at: int | None = None,
        private_key=None,
    ) -> str:
        now = issued_at if issued_at is not None else int(time.time())
        return jwt.encode(
            {
                "sub": subject,
                "iss": ISSUER,
                "aud": [audience, ISSUER],
                "iat": now,
                "exp": now + 300,
                "scp": scopes if scopes is not None else ["llm:invoke"],
            },
            private_key or self.private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    def _signing_key_patch(self):
        return patch.object(
            pocketid_auth,
            "_get_signing_key",
            AsyncMock(return_value=self.public_key),
        )

    async def test_valid_token_maps_to_restricted_user(self):
        user = SimpleNamespace(
            user_id="litellm-user-id",
            user_email="person@example.com",
            models=["allowed-model"],
            spend=1.25,
            max_budget=10,
            tpm_limit=1000,
            rpm_limit=10,
        )

        with (
            self._signing_key_patch(),
            patch.object(
                pocketid_auth,
                "_resolve_user",
                AsyncMock(return_value=user),
            ) as resolve_user,
        ):
            token = self._token()
            result = await pocketid_auth.user_api_key_auth(_request(), token)

        resolve_user.assert_awaited_once_with("pocket-id-user-id", token)
        self.assertEqual(result.user_id, "litellm-user-id")
        self.assertEqual(result.allowed_routes, ["openai_routes"])
        self.assertEqual(result.models, ["allowed-model"])
        self.assertEqual(result.user_max_budget, 10)
        self.assertIsNone(result.max_parallel_requests)

    async def test_token_policy_is_enforced(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cases = (
            ("forged signature", self._token(private_key=other_key), "401"),
            (
                "wrong audience",
                self._token(audience="https://other.example.com"),
                "401",
            ),
            (
                "expired",
                self._token(issued_at=int(time.time()) - 600),
                "401",
            ),
            ("missing permission", self._token(scopes=["openid"]), "403"),
            (
                "machine identity",
                self._token(subject="client-oidc-client-id"),
                "403",
            ),
        )

        with self._signing_key_patch():
            for name, token, expected_code in cases:
                with (
                    self.subTest(name=name),
                    self.assertRaises(ProxyException) as raised,
                ):
                    await pocketid_auth.user_api_key_auth(_request(), token)

                self.assertEqual(raised.exception.code, expected_code)

    def test_openai_routes_are_allowed_and_management_routes_are_denied(self):
        auth = UserAPIKeyAuth(
            allowed_routes=[LiteLLMRoutes.openai_routes.name],
        )

        for path in (
            "/v1/models",
            "/v1/chat/completions",
            "/v1/audio/speech",
            "/v1/images/generations",
            "/v1/files",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    RouteChecks.should_call_route(
                        route=path,
                        valid_token=auth,
                        request=_request(path=path),
                    )
                )

        for path in ("/key/list", "/spend/logs", "/user/info"):
            with (
                self.subTest(path=path),
                self.assertRaises(HTTPException) as raised,
            ):
                RouteChecks.should_call_route(
                    route=path,
                    valid_token=auth,
                    request=_request(path=path),
                )

            self.assertEqual(raised.exception.status_code, 403)

    async def test_existing_user_is_linked_by_email(self):
        existing_user = SimpleNamespace(user_id="existing-litellm-user")
        lookup_user = AsyncMock(
            side_effect=[
                ValueError("subject not linked"),
                existing_user,
            ]
        )
        fetch_profile = AsyncMock(return_value={"email": "person@example.com"})

        with (
            patch.object(pocketid_auth, "_lookup_user", lookup_user),
            patch.object(pocketid_auth, "_fetch_user_profile", fetch_profile),
        ):
            result = await pocketid_auth._resolve_user(
                "pocket-id-user-id",
                "access-token",
            )

        self.assertIs(result, existing_user)
        lookup_user.assert_has_awaits(
            [
                call(
                    subject="pocket-id-user-id",
                    email=None,
                    create=False,
                ),
                call(
                    subject="pocket-id-user-id",
                    email="person@example.com",
                    create=True,
                ),
            ]
        )

    async def test_userinfo_outage_returns_503(self):
        with (
            patch.object(
                pocketid_auth.httpx.AsyncClient,
                "get",
                AsyncMock(side_effect=pocketid_auth.httpx.ConnectError("unavailable")),
            ),
            self.assertRaises(ProxyException) as raised,
        ):
            await pocketid_auth._fetch_user_profile(
                "access-token",
                "pocket-id-user-id",
            )

        self.assertEqual(raised.exception.code, "503")

    async def test_database_outage_returns_503(self):
        lookup_user = AsyncMock(
            side_effect=[
                ValueError("subject not linked"),
                ValueError("database unavailable"),
                ValueError("database unavailable"),
            ]
        )

        with (
            patch.object(pocketid_auth, "_lookup_user", lookup_user),
            patch.object(
                pocketid_auth,
                "_fetch_user_profile",
                AsyncMock(return_value={"email": "person@example.com"}),
            ),
            self.assertRaises(ProxyException) as raised,
        ):
            await pocketid_auth._resolve_user(
                "pocket-id-user-id",
                "access-token",
            )

        self.assertEqual(raised.exception.code, "503")

    async def test_jwks_outage_returns_503(self):
        with (
            patch.object(
                pocketid_auth._JWKS_CLIENT,
                "get_signing_key_from_jwt",
                side_effect=OSError("Pocket ID unavailable"),
            ),
            self.assertRaises(ProxyException) as raised,
        ):
            await pocketid_auth._get_signing_key("access-token")

        self.assertEqual(raised.exception.code, "503")

    async def test_only_get_liveliness_is_public(self):
        result = await pocketid_auth.user_api_key_auth(
            _request(path="/health/liveliness"),
            "",
        )
        self.assertIsNone(result.user_id)

        with self.assertRaises(ProxyException) as raised:
            await pocketid_auth.user_api_key_auth(
                _request(method="POST", path="/health/liveliness"),
                "",
            )

        self.assertEqual(raised.exception.code, "401")


if __name__ == "__main__":
    unittest.main()
