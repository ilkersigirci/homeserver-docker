#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

python3 - <<'PY'
import json
from pathlib import Path

package = json.loads(Path("package.json").read_text())
dependencies = package["dependencies"]
codex_acp_package = "@agentclientprotocol/codex-acp"
codex_acp_version = dependencies[codex_acp_package]
bridge_version = dependencies["stdio-to-ws"]

for name, version in (
    (codex_acp_package, codex_acp_version),
    ("stdio-to-ws", bridge_version),
):
    if version.startswith(("^", "~", ">", "<", "=")) or " " in version:
        raise SystemExit(f"{name} must be pinned to an exact version")

print(f"{codex_acp_version}-ws{bridge_version}")
PY
