"""Check that the gateway and backend images serve the routes this image's
patches and configuration rely on, as apps/litellm-stack.yml routes them."""

import sys
from collections.abc import Callable
from typing import Final

from starlette.routing import BaseRoute, Match

# The component entrypoints import their packages from the image's /app.
sys.path.insert(0, "/app")

from backend.main import _is_backend_route  # noqa: E402
from gateway.main import _is_gateway_route  # noqa: E402

from litellm.proxy._lazy_features import LAZY_FEATURES, register_all_features  # noqa: E402
from litellm.proxy.proxy_server import app  # noqa: E402

# (scope type, method, path). Traefik sends upstream's ingress gateway prefixes
# to the gateway and every other API path to the backend.
GATEWAY_ROUTES: Final = (
    ("http", "POST", "/v1/chat/completions"),
    ("http", "GET", "/v1/models"),
    ("http", "GET", "/v1/models/check-model"),
    ("http", "POST", "/models/check-model:generateContent"),
    ("http", "POST", "/v1/responses"),
    ("http", "GET", "/v1/responses/resp_check"),
    ("http", "POST", "/v1/responses/resp_check/cancel"),
    ("websocket", None, "/v1/responses"),
    ("websocket", None, "/v1/realtime"),
    ("http", "GET", "/v1/files"),
    ("http", "GET", "/v1/files/file-check"),
    ("http", "GET", "/v1/files/file-check/content"),
    ("http", "DELETE", "/v1/files/file-check"),
)
BACKEND_ROUTES: Final = (
    ("http", "GET", "/model/info"),
    ("http", "GET", "/v1/model/info"),
    ("http", "POST", "/key/generate"),
    ("http", "POST", "/key/sk-check/regenerate"),
    ("http", "POST", "/team/member_add"),
    ("http", "POST", "/team/member_update"),
    ("http", "GET", "/alerting/settings"),
    ("http", "GET", "/scim/v2/Users"),
    ("http", "GET", "/sso/key/generate"),
    ("http", "GET", "/sso/callback"),
    ("http", "GET", "/sso/debug/login"),
    ("http", "POST", "/mcp/"),
    ("http", "POST", "/check-server/mcp"),
    ("http", "GET", "/.well-known/litellm-ui-config"),
    ("http", "GET", "/spend/logs/ui"),
)


def _matches(route: BaseRoute, kind: str, method: str | None, path: str) -> bool:
    scope: Final[dict[str, object]] = {"type": kind, "path": path, "root_path": "", "headers": []}
    if method is not None:
        scope["method"] = method
    return route.matches(scope)[0] is Match.FULL


def main() -> None:
    # Components trim eager routes at startup; lazy features register on the
    # first matching request in whichever component receives it.
    eager: Final = tuple(app.router.routes)
    register_all_features(app)
    lazy_routes: Final = app.state.lazy_routes

    def served(keeps: Callable[[BaseRoute], bool], kind: str, method: str | None, path: str) -> bool:
        if any(keeps(route) and _matches(route, kind, method, path) for route in eager):
            return True
        return any(
            feature.matches(path) and any(_matches(r, kind, method, path) for r in lazy_routes[feature.module_path])
            for feature in LAZY_FEATURES
            if feature.module_path in lazy_routes
        )

    missing: Final = [
        f"{component}: {method or kind} {path}"
        for component, keeps, routes in (
            ("gateway", _is_gateway_route, GATEWAY_ROUTES),
            ("backend", _is_backend_route, BACKEND_ROUTES),
        )
        for kind, method, path in routes
        if not served(keeps, kind, method, path)
    ]
    assert not missing, missing
    print("Component route checks passed")


if __name__ == "__main__":
    main()
