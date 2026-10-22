"""Build-time checks for OIDC access tokens through LiteLLM's native JWT auth.

Runs the installed auth chain; mocks only the JWKS fetch, database, and spend reads.
"""

import asyncio
import json
import os
import ssl
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import litellm
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from litellm.proxy._types import LiteLLM_UserTable, ProxyException

_CONFIG_PATH = "/app/litellm-config/config.yaml"
_ISSUER = "https://pocketid.example.test"
_AUDIENCE = "https://llm.example.test"
_SUBJECT = "subject"
_KID = "oidc-test-key"
_MASTER_KEY = "sk-native-test"

# Mirror the JWT_* settings in apps/litellm.yml and configs/litellm/config.yaml.
_DISCOVERY_URL = f"{_ISSUER}/.well-known/openid-configuration"
_JWKS_URL = f"{_ISSUER}/.well-known/jwks.json"
_ENV = {
    "JWT_PUBLIC_KEY_URL": _DISCOVERY_URL,
    "JWT_ISSUER": _ISSUER,
    "JWT_AUDIENCE": _AUDIENCE,
}
_GENERAL_SETTINGS = {
    "enable_jwt_auth": True,
    "litellm_jwtauth": {
        "user_id_jwt_field": "sub",
        "user_id_upsert": True,
        "end_user_id_jwt_field": "sub",
        "custom_validate": "access_token.validate_claims",
        "enforce_rbac": True,
        "admin_allowed_routes": [],
    },
    "role_permissions": [
        {
            "role": "internal_user",
            "routes": ["openai_routes", "model_info_routes", "mcp_inference_routes", "/v1/models/*", "/models/*"],
        }
    ],
    "fail_closed_budget_enforcement": True,
}

_TOKEN_ROUTES = (
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/models",
    "/v1/models/allowed",
    "/models/allowed",
    "/model/info",
    "/v1/model/info",
)
_MCP_ROUTES = ("/mcp", "/mcp/", "/mcp/tools/list", "/mcp/tools/call", "/v1/mcp/tools")
_ADMIN_ROUTES = ("/key/generate", "/user/new", "/model/new", "/spend/logs", "/v1/mcp/server")

_MODELS = [
    {
        "model_name": name,
        "litellm_params": {"model": "openai/gpt-4o", "api_key": "DUMMY"},
        "model_info": {"id": model_id, **extra},
    }
    for name, model_id, extra in (
        ("allowed", "allowed", {}),
        ("denied", "denied", {}),
        ("allowed", "other-team-id", {"team_id": "other-team"}),
    )
]


def _token_fixture():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = _KID

    def token(*, key=private_key, kid=_KID, typ="at+jwt", **overrides):
        claims = {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": _SUBJECT,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "scope": "openid llm:invoke",
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid, "typ": typ})

    return token, public_jwk


def _app() -> FastAPI:
    from litellm.proxy import proxy_server
    from litellm.proxy.auth.user_api_key_auth import user_api_key_auth

    app = FastAPI()

    @app.exception_handler(ProxyException)
    async def proxy_error(_request, exc):
        return JSONResponse({"error": exc.message}, status_code=int(exc.code))

    app.add_api_route("/v1/models", proxy_server.model_list, methods=["GET"])
    app.add_api_route("/v1/models/{model_id}", proxy_server.model_info, methods=["GET"])
    app.add_api_route("/v1/model/info", proxy_server.model_info_v1, methods=["GET"])

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def auth_probe(request: Request, key=Depends(user_api_key_auth)):  # noqa: B008
        # Stop after authorization without calling a model provider.
        request.app.state.authorized = key
        return {"user_id": key.user_id, "user_role": key.user_role, "team_id": key.team_id, "end_user_id": key.end_user_id}

    return app


async def _first_frame_allowed(authorization: str) -> bool:
    """Authorize a Responses WebSocket that names its model in the first frame."""
    from litellm.proxy import proxy_server
    from litellm.proxy.auth.user_api_key_auth import user_api_key_auth_websocket
    from litellm.proxy.response_api_endpoints.endpoints import _enforce_responses_ws_first_frame_model_auth

    headers = [(b"authorization", authorization.encode())]
    scope = {"path": "/v1/responses", "query_string": b"", "headers": headers}
    websocket = WebSocket({**scope, "type": "websocket"}, receive=AsyncMock(), send=AsyncMock())
    handshake = await user_api_key_auth_websocket(websocket)
    try:
        await _enforce_responses_ws_first_frame_model_auth(
            request=Request({**scope, "type": "http", "method": "POST"}),
            model="allowed",
            user_api_key_dict=handshake,
            llm_router=proxy_server.llm_router,
        )
    except litellm.BudgetExceededError:
        return False
    return True


async def _verify_tokens(call, token, load_user) -> None:
    # The license gate is gone, the verified `sub` is the Internal User, first
    # use upserts it, and a client-supplied `user` cannot replace it.
    response = await call(user="someone-else")
    expected = {"user_id": _SUBJECT, "user_role": "internal_user", "team_id": None, "end_user_id": _SUBJECT}
    assert response.json() == expected, response.text
    assert load_user.await_args.kwargs["user_id"] == _SUBJECT
    assert load_user.await_args.kwargs["user_id_upsert"] is True

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for invalid, status in (
        (token(aud="https://other.example.test"), 401),
        (token(iss="https://other.example.test"), 401),
        (token(exp=int(time.time()) - 60), 401),
        (token(exp=None), 401),
        (token(typ="JWT"), 401),
        (token(key=other_key), 401),
        (token(kid="unknown-key"), 401),
        (token(sub=None), 401),
        (token(sub=""), 401),
        (token(scope="openid other:scope"), 403),
        (token(scope=None, scp=["llm:invoke"]), 403),
    ):
        response = await call(headers={"Authorization": f"Bearer {invalid}"})
        assert response.status_code == status, response.text

    # LiteLLM's built-in admin scope grants no route (admin_allowed_routes: []).
    admin_scoped = {"Authorization": f"Bearer {token(scope='openid llm:invoke litellm_proxy_admin')}"}
    for path in ("/v1/responses", *_ADMIN_ROUTES):
        response = await call(headers=admin_scoped, path=path)
        assert response.status_code == 401, (path, response.text)

    # Master and virtual keys keep LiteLLM's native authentication.
    response = await call(headers={"Authorization": f"Bearer {_MASTER_KEY}"}, model="denied")
    assert response.json()["user_role"] == "proxy_admin", response.text


async def _verify_profile(call, token, load_user, user) -> None:
    """Tokens update the user's email and alias as the Admin UI SSO login does.

    The email follows the provider, the alias is filled only while empty,
    unchanged values and missing claims write nothing, and the email never
    selects the user.
    """
    import litellm.proxy.auth.handle_jwt as jwt_module
    from litellm.proxy import proxy_server

    update = AsyncMock()
    repository = SimpleNamespace(table=SimpleNamespace(update=update))
    cases = (
        ({"email": "Ada@Example.test", "name": "Ada"}, {"user_email": "ada@example.test", "user_alias": "Ada"}),
        ({"email": "ada@example.test", "name": "Ada"}, None),
        ({"email": "new@example.test", "name": "Renamed"}, {"user_email": "new@example.test"}),
        ({}, None),
    )
    with (
        patch.object(proxy_server, "prisma_client", object()),
        patch.object(jwt_module, "UserRepository", lambda _client: repository),
    ):
        for claims, written in cases:
            update.reset_mock()
            response = await call(headers={"Authorization": f"Bearer {token(**claims)}"})
            assert response.status_code == 200, (claims, response.text)
            assert load_user.await_args.kwargs["user_email"] is None, claims
            if written is None:
                update.assert_not_awaited()
            else:
                update.assert_awaited_once_with(where={"user_id": _SUBJECT}, data=written)
    user.user_email = user.user_alias = None


async def _verify_routes(call, user) -> None:
    """Tokens reach inference, model metadata, and MCP tools, never management.

    This holds even for a user whose LiteLLM role is proxy_admin.
    """
    for role in ("internal_user", "proxy_admin"):
        user.user_role = role
        for path in _TOKEN_ROUTES:
            response = await call(path=path)
            assert response.status_code == 200, (role, path, response.text)
        for path in _ADMIN_ROUTES:
            response = await call(path=path)
            assert response.status_code == 403, (role, path, response.text)
    response = await call(model="denied")
    assert response.json()["user_role"] == "proxy_admin", response.text
    user.user_role = "internal_user"


async def _verify_models(client, call, user, headers) -> None:
    """The user's models govern invocation, client fallbacks, listings, and direct model lookups."""

    async def model_info_ids(model_id=None):
        params = {"litellm_model_id": model_id} if model_id else {}
        response = await client.get("/v1/model/info", headers=headers, params=params)
        assert response.status_code == 200, response.text
        rows = response.json()["data"]
        assert all("api_key" not in row["litellm_params"] for row in rows)
        return {row["model_info"]["id"] for row in rows}

    # The unrestricted case runs last so the budget checks cover it.
    for user_models, visible in ((["allowed"], {"allowed"}), ([], {"allowed", "denied"})):
        user.models = user_models
        response = await client.get("/v1/models", headers=headers)
        assert {row["id"] for row in response.json()["data"]} == visible, response.text
        for model in ("allowed", "denied"):
            response = await call(model=model)
            assert response.status_code == (200 if model in visible else 403), response.text
            response = await client.get(f"/v1/models/{model}", headers=headers)
            assert response.status_code == (200 if model in visible else 404), response.text

        # Removal check for patches/temporary/jwt-fallback-access.patch.
        for fallback in ({"fallbacks": ["denied"]}, {"context_window_fallbacks": [{"allowed": ["denied"]}]}):
            response = await call(path="/v1/chat/completions", **fallback)
            assert response.status_code == (200 if "denied" in visible else 403), (fallback, response.text)
        response = await call(path="/v1/chat/completions", fallbacks=["allowed"])
        assert response.status_code == 200, response.text

        # Removal check for patches/temporary/model-info-access.patch.
        assert await model_info_ids() == visible
        assert await model_info_ids("denied") == visible & {"denied"}
        assert await model_info_ids("other-team-id") == set()


async def _verify_budgets(call, user, authorization) -> None:
    # Budget refusals use LiteLLM's default budget_exceeded_status_code.
    assert await _first_frame_allowed(authorization)
    user.model_max_budget = {"allowed": {"max_budget": 0, "budget_duration": "1d"}}
    response = await call()
    assert response.status_code == 422, response.text
    # Removal check for patches/temporary/responses-websocket-budget.patch.
    assert not await _first_frame_allowed(authorization), "Responses WebSocket bypassed the user's model budget"
    user.model_max_budget = {}
    user.max_budget = 0
    response = await call()
    assert response.status_code == 422, response.text


async def _verify_mcp(call, app, user) -> None:
    """MCP routes resolve servers exactly as LiteLLM's own MCP login for the user.

    A user reaches open servers and their own and their teams' grants; an admin
    gets LiteLLM's admin view. Membership of a single team must not attach that
    team's policy to other routes.
    """
    import litellm.proxy.auth.auth_checks as auth_checks
    import litellm.proxy.auth.handle_jwt as jwt_module
    import litellm.proxy.auth.user_api_key_auth as auth_module
    from litellm.proxy import proxy_server
    from litellm.proxy._experimental.mcp_server.auth.user_api_key_auth_mcp import MCPRequestHandler
    from litellm.proxy._experimental.mcp_server.mcp_server_manager import global_mcp_server_manager
    from litellm.proxy._types import LiteLLM_ObjectPermissionTable, LiteLLM_TeamTable, Member
    from litellm.types.mcp_server.mcp_server_manager import MCPServer

    servers = {
        name: MCPServer(server_id=name, name=name, transport="http", allow_all_keys=name == "open")
        for name in ("open", "user_grant", "team_grant", "closed")
    }
    user.teams = ["reports"]
    team = LiteLLM_TeamTable(
        team_id="reports",
        members_with_roles=[Member(user_id=_SUBJECT, role="user")],
        object_permission=LiteLLM_ObjectPermissionTable(object_permission_id="team-grants", mcp_servers=["team_grant"]),
    )
    with ExitStack() as stack:
        for patcher in (
            patch.object(auth_checks, "get_user_object", AsyncMock(return_value=user)),
            patch.object(auth_checks, "get_team_object", AsyncMock(return_value=team)),
            patch.object(auth_checks, "get_team_membership", AsyncMock(return_value=None)),
            patch.object(jwt_module, "get_team_object", AsyncMock(return_value=team)),
            patch.object(jwt_module, "get_team_membership", AsyncMock(return_value=None)),
            patch.object(auth_module, "get_team_object", AsyncMock(return_value=team)),
            patch.object(proxy_server, "prisma_client", object()),
            patch.dict(global_mcp_server_manager.config_mcp_servers, servers, clear=True),
        ):
            stack.enter_context(patcher)
        response = await call()
        assert response.status_code == 200 and response.json()["team_id"] is None, response.text
        for role, servers_for_role in (
            ("internal_user", {"open", "user_grant", "team_grant"}),
            ("proxy_admin", set(servers)),
        ):
            user.user_role = role
            # An admin without explicit MCP permissions gets LiteLLM's admin view.
            user.object_permission = (
                None
                if role == "proxy_admin"
                else LiteLLM_ObjectPermissionTable(object_permission_id="user-grants", mcp_servers=["user_grant"])
            )
            login = await MCPRequestHandler.reload_admitted_user(_SUBJECT)
            assert set(await global_mcp_server_manager.get_allowed_mcp_servers(login)) == servers_for_role, role
            for path in _MCP_ROUTES:
                response = await call(path=path)
                assert response.status_code == 200, (role, path, response.text)
                authorized = app.state.authorized
                assert (authorized.user_id, authorized.user_role) == (_SUBJECT, role), path
                allowed = await global_mcp_server_manager.get_allowed_mcp_servers(authorized)
                assert set(allowed) == servers_for_role, (role, path, allowed)


async def _verify() -> None:
    import litellm.proxy.auth.handle_jwt as jwt_module
    import litellm.proxy.auth.user_api_key_auth as auth_module
    from litellm.caching.caching import DualCache
    from litellm.proxy import proxy_server
    from litellm.proxy.hooks.model_max_budget_limiter import _PROXY_VirtualKeyModelMaxBudgetLimiter

    token, public_jwk = _token_fixture()
    headers = {"Authorization": f"Bearer {token()}"}
    user = LiteLLM_UserTable(user_id=_SUBJECT, user_role="internal_user", models=["allowed"], spend=0, max_budget=10)
    load_user = AsyncMock(return_value=user)
    # LiteLLM follows the discovery document's jwks_uri to the signing keys.
    discover = AsyncMock(return_value=_JWKS_URL)
    fetch_keys = AsyncMock(return_value=[public_jwk])

    async def user_spend(**_kwargs):
        return user.spend

    with ExitStack() as stack:
        for patcher in (
            patch.dict(os.environ, _ENV),
            patch.object(proxy_server, "general_settings", dict(_GENERAL_SETTINGS)),
            patch.object(proxy_server, "user_config_file_path", _CONFIG_PATH),
            patch.object(proxy_server, "premium_user", False),
            patch.object(proxy_server, "master_key", _MASTER_KEY),
            patch.object(proxy_server, "llm_router", litellm.Router(model_list=_MODELS)),
            patch.object(proxy_server, "llm_model_list", _MODELS),
            patch.object(proxy_server, "user_model", None),
            patch.object(proxy_server, "prisma_client", None),
            patch.object(proxy_server, "get_current_spend", user_spend),
            patch.object(proxy_server, "model_max_budget_limiter", _PROXY_VirtualKeyModelMaxBudgetLimiter(DualCache())),
            patch.object(proxy_server, "_get_caller_byok_team_scope", AsyncMock(return_value=set())),
            patch.object(proxy_server.jwt_handler, "_fetch_jwks_uri_from_discovery", discover),
            patch.object(proxy_server.jwt_handler, "_fetch_jwks_keys", fetch_keys),
            patch.object(jwt_module, "get_user_object", load_user),
            patch.object(jwt_module, "get_end_user_object", AsyncMock(return_value=None)),
            patch.object(auth_module, "get_user_object", AsyncMock(return_value=user)),
            patch.object(auth_module, "get_end_user_object", AsyncMock(return_value=None)),
            patch.object(auth_module, "get_global_proxy_spend", AsyncMock(return_value=0)),
        ):
            stack.enter_context(patcher)
        proxy_server.ProxyStartupEvent._initialize_jwt_auth(
            general_settings=proxy_server.general_settings,
            prisma_client=None,
            user_api_key_cache=proxy_server.user_api_key_cache,
        )
        app = _app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://litellm.invalid") as client:

            async def call(headers=headers, model="allowed", path="/v1/responses", **body):
                return await client.post(path, headers=headers, json={"model": model, "input": "hi", **body})

            await _verify_tokens(call, token, load_user)
            discover.assert_awaited_with(_DISCOVERY_URL)
            fetch_keys.assert_awaited_with(_JWKS_URL)
            await _verify_profile(call, token, load_user, user)
            await _verify_routes(call, user)
            await _verify_models(client, call, user, headers)
            await _verify_budgets(call, user, headers["Authorization"])
            user.max_budget = 10
            await _verify_mcp(call, app, user)


def _verify_jwks_tls() -> None:
    """The JWKS client follows LiteLLM's SSL_VERIFY.

    Removal check for patches/temporary/jwt-jwks-ssl.patch.
    """
    from litellm.proxy.auth.handle_jwt import JWTHandler

    for verify, verified in ((None, True), ("true", True), ("false", False)):
        env = {name: value for name, value in os.environ.items() if name != "SSL_VERIFY"}
        if verify is not None:
            env["SSL_VERIFY"] = verify
        with patch.dict(os.environ, env, clear=True):
            context = JWTHandler().http_handler.client._transport._pool._ssl_context
        assert context.check_hostname is verified, verify
        assert (context.verify_mode == ssl.CERT_REQUIRED) is verified, verify


def main() -> None:
    _verify_jwks_tls()
    asyncio.run(_verify())
    print("JWT Internal User authorization checks passed")


if __name__ == "__main__":
    main()
