#!/usr/bin/env python3
"""Render Marimo's repository configuration with Compose-provided credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib


class ConfigRenderError(ValueError):
    """Raised when the configuration inputs do not satisfy the contract."""


def render_config(
    config: str,
    secrets: str,
    *,
    config_source: str = "configuration",
    secrets_source: str = "secrets",
) -> str:
    """Substitute validated secrets and return valid TOML configuration."""
    try:
        parsed_secrets = tomllib.loads(secrets)
    except tomllib.TOMLDecodeError as error:
        raise ConfigRenderError(
            f"{secrets_source} is not valid TOML: {error}"
        ) from error

    try:
        provider = parsed_secrets["ai"]["custom_providers"]["aigateway"]
        api_key = provider["api_key"]
        base_url = provider["base_url"]
    except (KeyError, TypeError) as error:
        raise ConfigRenderError(
            f"{secrets_source} has an invalid aigateway provider"
        ) from error

    replacements = (
        ("__AIGATEWAY_API_KEY__", api_key, "api_key"),
        ("__AIGATEWAY_BASE_URL__", base_url, "base_url"),
    )
    rendered = config
    for placeholder, value, field in replacements:
        if not isinstance(value, str) or not value:
            raise ConfigRenderError(f"{secrets_source} has an empty {field}")

        token = json.dumps(placeholder)
        if rendered.count(token) != 1:
            raise ConfigRenderError(
                f"{config_source} must contain {token} exactly once"
            )
        rendered = rendered.replace(token, json.dumps(value, ensure_ascii=False))

    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as error:
        raise ConfigRenderError(
            f"{config_source} does not render as valid TOML: {error}"
        ) from error

    return rendered


def write_atomic(target: Path, content: str) -> None:
    """Atomically replace target with a mode-0600 UTF-8 text file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def render_files(config: Path, secrets: Path, output: Path) -> None:
    """Read, render, and atomically write the Marimo configuration."""
    rendered = render_config(
        config.read_text(encoding="utf-8"),
        secrets.read_text(encoding="utf-8"),
        config_source=str(config),
        secrets_source=str(secrets),
    )
    write_atomic(output, rendered)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--secrets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        render_files(args.config, args.secrets, args.output)
    except (ConfigRenderError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
