"""Remove proprietary source and packaging entries from an upstream checkout."""

import re
import shutil
import sys
import tomllib
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]).resolve(strict=True)
    if root == Path(root.anchor) or not (root / "litellm/proxy").is_dir():
        raise ValueError("expected a LiteLLM source checkout")

    for relative in ("litellm/proxy/enterprise", "enterprise", "tests/enterprise"):
        path = root / relative
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)

    project = root / "pyproject.toml"
    content = project.read_text()
    content = re.sub(
        r"^.*(?:litellm-enterprise|litellm/proxy/enterprise).*\n",
        "",
        content,
        flags=re.MULTILINE,
    )
    content = content.replace('"enterprise", ', "").replace(', "enterprise"', "")
    metadata = tomllib.loads(content)
    assert "enterprise" not in metadata["tool"]["uv"]["workspace"]["members"]
    assert "litellm-enterprise" not in content
    project.write_text(content)

    # Preserve upstream's dependency pins; remove only the enterprise workspace
    # package and its references, including the manifest and requires-dist.
    lock = root / "uv.lock"
    sections = lock.read_text().split("[[package]]\n")
    sections = [
        section
        for section in sections
        if not section.startswith('name = "litellm-enterprise"\n')
    ]
    content = "[[package]]\n".join(sections)
    content = re.sub(r'^.*"litellm-enterprise".*\n', "", content, flags=re.MULTILINE)
    assert "litellm-enterprise" not in content
    tomllib.loads(content)
    lock.write_text(content)

    # The build uses the OSS dashboard directly, without enterprise overrides.
    (root / "docker/build_admin_ui.sh").write_text(
        '#!/bin/sh\nset -eu\necho "Admin UI - using default LiteLLM UI"\n'
    )


if __name__ == "__main__":
    main()
