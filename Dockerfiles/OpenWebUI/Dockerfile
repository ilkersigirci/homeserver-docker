ARG IMAGE_VERSION=v0.12.5-slim
FROM ghcr.io/open-webui/open-webui:${IMAGE_VERSION}@sha256:9a4db3e6c8d6174d4ed8952304115e90dcc36e9a8b98c2f8984eab321f29505e

RUN --mount=type=bind,source=patches,target=/tmp/open-webui-patches \
    set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends patch; \
    for patch_file in /tmp/open-webui-patches/*.patch; do \
      patch --batch --forward --fuzz=0 -p1 < "${patch_file}"; \
    done; \
    apt-get purge -y --auto-remove patch; \
    rm -rf /var/lib/apt/lists/*

# Importing Open WebUI writes its database, static assets, and bytecode; keep
# them out of the image.
RUN --mount=type=bind,source=tests,target=/tmp/open-webui-tests \
    set -eux; \
    export DATA_DIR=/tmp/open-webui-build-check WEBUI_SECRET_KEY=build-check PYTHONDONTWRITEBYTECODE=1; \
    export STATIC_DIR="${DATA_DIR}/static"; \
    mkdir -p "${STATIC_DIR}"; \
    python -m unittest discover -s /tmp/open-webui-tests -v; \
    rm -rf "${DATA_DIR}"
