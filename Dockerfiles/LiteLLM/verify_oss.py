"""Check stripped source, or the installed runtime when no source path is given."""

import ast
import importlib.metadata
import importlib.util
import sys
import tomllib
from pathlib import Path


def main() -> None:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve(strict=True)
        for name in ("pyproject.toml", "uv.lock"):
            content = (root / name).read_text()
            tomllib.loads(content)
            assert "litellm-enterprise" not in content, name
    else:
        import litellm
        import litellm.proxy.proxy_server

        root = Path(litellm.__file__).resolve().parent.parent
        assert importlib.util.find_spec("litellm_enterprise") is None
        assert not any(
            dist.metadata["Name"].lower().replace("_", "-") == "litellm-enterprise"
            for dist in importlib.metadata.distributions()
        )
        assert not Path("/app/enterprise").exists()

    for relative in ("enterprise", "litellm/proxy/enterprise", "tests/enterprise"):
        path = root / relative
        assert not path.exists() and not path.is_symlink(), path

    for path in (root / "litellm").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("litellm_enterprise"), path
            elif isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith("litellm_enterprise") for alias in node.names
                ), path

    sso = root / "litellm/proxy/management_endpoints/ui_sso.py"
    tree = ast.parse(sso.read_text())
    login = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "google_login"
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "count_billable_users"
        for node in ast.walk(login)
    ), "SSO login still counts users for the free-tier gate"
    assert "free SSO user" not in sso.read_text()
    print("OSS source and SSO checks passed")


if __name__ == "__main__":
    main()
