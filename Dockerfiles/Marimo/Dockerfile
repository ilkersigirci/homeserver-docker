# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
ARG UV_VERSION=0.11.29-python3.13-trixie-slim
ARG NODE_VERSION=24.18.0-bookworm-slim

FROM node:${NODE_VERSION}@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS node-runtime

FROM ghcr.io/astral-sh/uv:${UV_VERSION}@sha256:0b973c14a35cb0dc8fe63a2e8c9919fd797ac566de13090fcf0df4a6b3994b78 AS project

ENV UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /opt/marimo

COPY pyproject.toml uv.lock .python-version ./

# The sandbox extra declares uv. Keep its package metadata, but use the same
# pinned binaries already supplied by the uv base instead of storing them twice.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    UV_CACHE_DIR=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project \
    && test "$(.venv/bin/uv --version | cut -d ' ' -f 2)" = \
      "$(uv --version | cut -d ' ' -f 2)" \
    && rm .venv/bin/uv .venv/bin/uvx

COPY render_config.py ./

FROM ghcr.io/astral-sh/uv:${UV_VERSION}@sha256:0b973c14a35cb0dc8fe63a2e8c9919fd797ac566de13090fcf0df4a6b3994b78

ENV HOME=/tmp/marimo-home \
    PATH=/opt/marimo/.venv/bin:/workspace/.local/bin:$PATH \
    TMPDIR=/workspace/.cache/marimo/tmp \
    UV_CACHE_DIR=/workspace/.cache/uv \
    UV_PYTHON_BIN_DIR=/workspace/.local/bin \
    UV_PYTHON_INSTALL_DIR=/workspace/.local/share/uv/python \
    XDG_CACHE_HOME=/workspace/.cache \
    XDG_CONFIG_HOME=/tmp/marimo-home/.config \
    XDG_DATA_HOME=/workspace/.local/share

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

RUN groupadd --system marimo \
    && useradd \
      --system \
      --gid marimo \
      --no-create-home \
      --home-dir /tmp/marimo-home \
      --shell /usr/sbin/nologin \
      marimo \
    && mkdir -p /workspace \
    && chown marimo:marimo /workspace \
    && chmod 1777 /tmp

COPY --from=project --chown=marimo:marimo /opt/marimo/.venv/ /opt/marimo/.venv/
COPY --from=project --chown=marimo:marimo /opt/marimo/render_config.py /opt/marimo/render_config.py
COPY --chmod=0755 healthcheck.py /usr/local/bin/marimo-healthcheck
COPY --chmod=0755 entrypoint.sh /usr/local/bin/marimo-entrypoint

USER marimo:marimo
WORKDIR /workspace

EXPOSE 8080

HEALTHCHECK --interval=5m --timeout=5s --start-period=45s --start-interval=5s --retries=3 \
  CMD ["/usr/local/bin/marimo-healthcheck"]

ENTRYPOINT ["/usr/local/bin/marimo-entrypoint"]
CMD ["marimo", "edit", "--sandbox", "/workspace/projects", "--headless", "--host", "0.0.0.0", "--port", "8080", "--session-ttl", "300"]
