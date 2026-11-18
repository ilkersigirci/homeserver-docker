ARG IMAGE_VERSION=v0.13.4-slim
FROM ghcr.io/open-webui/open-webui:${IMAGE_VERSION}@sha256:0c4439e78c24c85e3e7a41936771d3b02f0df38daf28a086cd83ca74804f7676

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
