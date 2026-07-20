# Marimo Sandboxed Home

This image runs Marimo's native **Sandboxed Home** over
`/workspace/projects`. The launcher environment is immutable and contains
Marimo's sandbox and editor-AI dependencies plus ty and the Node runtime used
by Marimo's LSP transport. Application dependencies do not belong in the
image.

Compose bind-mounts `$REPO_PATH/data/marimo` at `/workspace`. On first start,
the entrypoint creates this persistent layout without overwriting existing
files:

```text
/workspace/
├── projects/                    # Project folders and notebook source
├── .cache/
│   ├── marimo/tmp/              # Ephemeral per-notebook environments
│   └── uv/                      # Persistent uv package cache
└── .local/
    ├── bin/                     # uv-managed Python executables
    └── share/uv/python/         # uv-managed Python installations
```

Create the host directory with ownership matching `PUID:PGID` before the first
start. The image build never copies its launcher environment into the bind
mount and does not run `uv sync` at container startup.

## One isolated environment per notebook

This is the default and most reproducible mode. Open the Marimo home page,
create folders such as `forecasting/` and `experiments/`, then create notebooks
inside them. Each notebook gets an environment on demand from its own PEP 723
header. Importing a package or using Marimo's package panel updates only that
notebook.

The same metadata can be managed from a shell:

```bash
uv add --script /workspace/projects/forecasting/analysis.py pandas altair
uv remove --script /workspace/projects/forecasting/analysis.py altair
uv run /workspace/projects/forecasting/analysis.py
```

Two notebooks may pin incompatible versions of the same package because their
environments are isolated. uv reuses the persistent download cache, so shared
artifacts are not downloaded for every notebook. The sandbox directory and uv
cache share the `/workspace` filesystem, allowing uv to link cached package
files instead of copying them into every environment. Sandbox directories are
removed when their sessions end, and the entrypoint removes leftovers from an
interrupted container before Marimo starts.

## One shared environment per project

When several notebooks are part of one application or library, keep a normal
uv project in a subdirectory:

```text
/workspace/projects/forecasting/
├── pyproject.toml
├── uv.lock
├── .venv/
├── analysis.py
└── report.py
```

Manage that project normally with `uv add`, `uv remove`, `uv lock`, and
`uv sync`. Point each notebook at the project's environment with inline
metadata:

```python
# /// script
# [tool.marimo.venv]
# path = ".venv"
# writable = false
# ///
```

`writable = false` keeps uv as the sole owner of the shared environment. Use
notebook-level PEP 723 dependencies instead when notebooks in the same folder
need incompatible packages.

## Python versions

The launcher uses Python 3.13. A notebook or uv project may request another
supported Python version through `requires-python` or `.python-version`. uv
downloads missing interpreters into `/workspace/.local/share/uv/python`, so
they survive container replacement without increasing the image size.

## Configuration

Compose mounts `$REPO_PATH/configs/marimo/marimo.toml` read-only at
`/etc/marimo/marimo.toml`. Copy `configs/marimo/secrets.toml.example` to the
Git-ignored `configs/marimo/secrets.toml`, fill in the gateway values, and set
its mode to `0600`. Compose mounts it as the read-only `marimo_ai` secret at
`/run/secrets/marimo_ai`; set `MARIMO_AI_SECRETS_FILE` to override the host
path. On every start, a dedicated renderer replaces the config's gateway
placeholders from that secret and atomically writes the rendered configuration
with mode `0600` to
`/tmp/marimo-home/.config/marimo/marimo.toml`. This keeps settings in Git,
credentials out of Git and the container environment, and the rendered secret
on tmpfs.

Settings UI changes affect only the rendered file and are reset on restart;
edit `configs/marimo/marimo.toml` for durable changes. The launcher installs
Marimo's upstream AI dependency directly instead of using the much larger
`marimo[recommended]` extra. Data libraries still belong in notebook or
project dependencies.

## External Codex agent

`apps/marimo.yml` runs the WebSocket bridge and Codex adapter separately.
Both services bind `$REPO_PATH/data/marimo` at `/workspace`, so the absolute
paths Marimo sends in ACP sessions resolve identically in Codex. Compose waits
for the ACP bridge to become healthy before starting Marimo. The browser
connects to `wss://marimo.$DOMAINNAME:3021/message`; Traefik routes that
entrypoint to the ACP service and Tinyauth protects the handshake.

Keep port 3021 unforwarded at the internet edge and ensure internal DNS resolves
the Marimo hostname to `$LOCAL_STATIC_IP`. See
`Dockerfiles/CodexAcp/README.md` for authentication and runtime details.

Marimo creates sandboxed notebook environments under
`/workspace/.cache/marimo/tmp` through `TMPDIR`. This keeps them on the same
filesystem as `/workspace/.cache/uv`, which avoids full package copies when uv
can link from its cache. Do not store durable data there. `/tmp` remains an
ephemeral tmpfs for the rendered configuration and home state.

## Commands

```bash
# Native multi-notebook home page (the image default)
marimo edit --sandbox /workspace/projects --headless --host 0.0.0.0

# Validate notebook source without executing it
marimo check /workspace/projects

# Run one notebook as a read-only app in its isolated environment
marimo run --sandbox /workspace/projects/forecasting/analysis.py
```

The image entrypoint enables Marimo authentication with `--token` and
`--token-password` when the `TOKEN` environment variable is non-empty. Without
`TOKEN`, it passes `--no-token` because Traefik and Tinyauth protect the Compose
route. Do not expose port 8080 directly without setting `TOKEN` or adding other
Marimo authentication.

## References

- [Sandboxed Home](https://docs.marimo.io/guides/editor_features/home/#sandboxed-home)
- [Inlining dependencies](https://docs.marimo.io/guides/package_management/inlining_dependencies/)
- [Notebooks in existing projects](https://docs.marimo.io/guides/package_management/notebooks_in_projects/)
- [Using uv](https://docs.marimo.io/guides/package_management/using_uv/)
- [Marimo configuration](https://docs.marimo.io/guides/configuration/)
- [Marimo external agents](https://docs.marimo.io/guides/editor_features/agents/)
- [uv Python versions](https://docs.astral.sh/uv/concepts/python-versions/)
