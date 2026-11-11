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
        # UserRepository.upsert_user caps new users at five only inside this scope.
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "free_sso_user_creation"
            for node in ast.walk(tree)
        ), f"{path} still applies the free-tier SSO user cap"

    sso = root / "litellm/proxy/management_endpoints/ui_sso.py"
    assert "count_billable_users" not in sso.read_text(), "SSO still counts users for the free-tier gate"
    print("OSS source and SSO checks passed")


if __name__ == "__main__":
    main()
