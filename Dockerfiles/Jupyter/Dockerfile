# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
ARG IMAGE_VERSION=0.11.28-python3.13-trixie-slim

FROM ghcr.io/astral-sh/uv:${IMAGE_VERSION}@sha256:08477888ac23d6cfbeb8c7dc6fc70cf297fd38b7bf35522be33ce832750ca242

ENV HOME=/tmp/jupyter-home \
    IPYTHONDIR=/jupyter/ipython \
    JUPYTER_CONFIG_DIR=/jupyter/config \
    JUPYTER_DATA_DIR=/jupyter/data \
    JUPYTERLAB_SETTINGS_DIR=/jupyter/lab/user-settings \
    JUPYTERLAB_WORKSPACES_DIR=/jupyter/lab/workspaces \
    JUPYTER_PORT=8888 \
    JUPYTER_RUNTIME_DIR=/tmp/jupyter-runtime \
    PATH=/opt/jupyter/.venv/bin:$PATH \
    UV_CACHE_DIR=/workspace/.cache/uv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    XDG_CACHE_HOME=/workspace/.cache

WORKDIR /opt/jupyter

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    UV_CACHE_DIR=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/jupyter/.venv \
    uv sync --locked --no-dev --no-install-project

COPY entrypoint.sh /usr/local/bin/jupyter-entrypoint
COPY register_uv_kernels.sh /usr/local/bin/jupyter-register-uv-kernels
COPY projects/ /opt/jupyter/projects/

RUN groupadd --system jupyter \
    && useradd \
      --system \
      --gid jupyter \
      --no-create-home \
      --home-dir /tmp/jupyter-home \
      --shell /usr/sbin/nologin \
      jupyter \
    && mkdir -p /jupyter /workspace \
    && chown jupyter:jupyter /jupyter /workspace \
    && chmod 1777 /tmp \
    && chmod 0755 \
      /usr/local/bin/jupyter-entrypoint \
      /usr/local/bin/jupyter-register-uv-kernels

USER jupyter:jupyter
WORKDIR /workspace

EXPOSE 8888

HEALTHCHECK --interval=5m --timeout=5s --start-period=45s --retries=3 \
  CMD ["curl", "-fsS", "--max-time", "3", "http://127.0.0.1:8888/api/"]

ENTRYPOINT ["/usr/local/bin/jupyter-entrypoint"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--ServerApp.root_dir=/workspace", "--ServerApp.allow_remote_access=True", "--ServerApp.trust_xheaders=True", "--IdentityProvider.token=", "--PasswordIdentityProvider.hashed_password="]
