#!/usr/bin/env python3
"""Initialize h and bootstrap local self-hosted Hypothesis data."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

from h import models
from h.cli import bootstrap
from h.search import config


@dataclass(frozen=True)
class Settings:
    app_url: str
    authority: str
    username: str
    email: str
    password: str
    admin: bool
    client_id: str
    client_name: str
    client_redirect_uri: str


def enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def load_settings() -> Settings:
    return Settings(
        app_url=require_env("APP_URL"),
        authority=require_env("AUTHORITY"),
        username=require_env("HYPOTHESIS_BOOTSTRAP_USERNAME"),
        email=require_env("HYPOTHESIS_BOOTSTRAP_EMAIL"),
        password=require_env("HYPOTHESIS_BOOTSTRAP_PASSWORD"),
        admin=enabled(require_env("HYPOTHESIS_BOOTSTRAP_ADMIN")),
        client_id=require_env("CLIENT_OAUTH_ID"),
        client_name=require_env("HYPOTHESIS_BOOTSTRAP_OAUTH_CLIENT_NAME"),
        client_redirect_uri=require_env("HYPOTHESIS_BOOTSTRAP_OAUTH_REDIRECT_URI"),
    )


def init_db() -> None:
    subprocess.run(
        [sys.executable, "-m", "h.scripts.init_db", "--create", "--stamp"],
        check=True,
    )


def bootstrap_request(app_url: str):
    request = bootstrap(app_url, False)
    config.init(request.es)
    return request


def bootstrap_user(request, settings: Settings) -> None:
    user = models.User.get_by_username(
        request.db, settings.username, settings.authority
    )
    if user is None:
        signup_service = request.find_service(name="user_signup")
        user = signup_service.signup(
            username=settings.username,
            email=settings.email,
            password=settings.password,
            authority=settings.authority,
            require_activation=False,
        )
        print(f"Created Hypothesis user {settings.username}@{settings.authority}")
    else:
        print(f"Hypothesis user {settings.username}@{settings.authority} already exists")
        password_service = request.find_service(name="user_password")
        password_service.update_password(user, settings.password)
        print(
            f"Updated password for Hypothesis user "
            f"{settings.username}@{settings.authority}"
        )

    if settings.admin:
        if not user.admin:
            user.admin = True
            print(
                f"Granted admin role to Hypothesis user "
                f"{settings.username}@{settings.authority}"
            )
        else:
            print(
                f"Hypothesis user {settings.username}@{settings.authority} "
                "is already an admin"
            )
    elif user.admin:
        user.admin = False
        print(
            f"Revoked admin role from Hypothesis user "
            f"{settings.username}@{settings.authority}"
        )


def bootstrap_oauth_client(request, settings: Settings) -> None:
    client = (
        request.db.query(models.AuthClient)
        .filter_by(id=settings.client_id)
        .one_or_none()
    )
    if client is None:
        client = models.AuthClient(
            id=settings.client_id,
            name=settings.client_name,
            authority=settings.authority,
        )
        client.grant_type = "authorization_code"
        client.redirect_uri = settings.client_redirect_uri
        request.db.add(client)
        print(f"Created OAuth client {settings.client_id} for {settings.authority}")
        return

    client.name = settings.client_name
    client.authority = settings.authority
    client.grant_type = "authorization_code"
    client.redirect_uri = settings.client_redirect_uri
    print(f"OAuth client {settings.client_id} already exists; ensured settings")


def main() -> int:
    settings = load_settings()
    init_db()
    request = bootstrap_request(settings.app_url)

    bootstrap_user(request, settings)
    bootstrap_oauth_client(request, settings)
    request.tm.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
