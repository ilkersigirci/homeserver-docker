#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

python3 - <<'PY'
import tomllib
from pathlib import Path

dependency_name = "marimo[sandbox]"
dependency_prefix = f"{dependency_name}=="
pyproject = tomllib.loads(Path("pyproject.toml").read_text())

for dependency in pyproject["project"]["dependencies"]:
    if dependency.startswith(dependency_prefix):
        marimo_version = dependency.removeprefix(dependency_prefix)
        break
else:
    raise SystemExit(f"{dependency_name} must be pinned with ==")

print(marimo_version)
PY
