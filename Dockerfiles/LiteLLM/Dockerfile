# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# renovate: datasource=github-tags depName=BerriAI/litellm
ARG IMAGE_VERSION=1.100.0
ARG UPSTREAM_COMMIT=e4f25265704e2b2c6cf6e81be2e4c5cffff896f4

FROM rust:1.94.1-slim-trixie@sha256:cf09adf8c3ebaba10779e5c23ff7fe4df4cccdab8a91f199b0c142c53fef3e1a AS rust

FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim@sha256:0b973c14a35cb0dc8fe63a2e8c9919fd797ac566de13090fcf0df4a6b3994b78 AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash openssl tzdata nodejs libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS source
ARG IMAGE_VERSION
ARG UPSTREAM_COMMIT
WORKDIR /app
ADD --checksum=${UPSTREAM_COMMIT} https://github.com/BerriAI/litellm.git#v${IMAGE_VERSION} /app
COPY strip_enterprise.py verify_oss.py base-sources.sha256 sso.patch litellm-auth.patch responses-streaming.patch responses-logging.patch /patches/
RUN apt-get update && apt-get install -y --no-install-recommends patch \
    && python3 /patches/strip_enterprise.py /app \
    && sha256sum -c /patches/base-sources.sha256 \
    && patch --batch --forward --fuzz=0 -p1 < /patches/sso.patch \
    && patch --batch --forward --fuzz=0 -p1 < /patches/litellm-auth.patch \
    && patch --batch --forward --fuzz=0 -p1 < /patches/responses-streaming.patch \
    && patch --batch --forward --fuzz=0 -p1 < /patches/responses-logging.patch \
    && python3 /patches/verify_oss.py /app

FROM --platform=$BUILDPLATFORM node:24.19-alpine3.24@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS ui
ENV NEXT_TELEMETRY_DISABLED=1 npm_config_fund=false npm_config_audit=false
WORKDIR /ui
COPY --from=source /app/ui/litellm-dashboard/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline
COPY --from=source /app/ui/litellm-dashboard/ ./
RUN npm run build

FROM base AS builder
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libssl-dev npm
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup \
    UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:/usr/local/cargo/bin:${PATH}"
COPY --from=source /app/pyproject.toml /app/uv.lock ./
COPY --from=source /app/litellm-proxy-extras/pyproject.toml litellm-proxy-extras/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --no-default-groups --no-editable \
      --extra proxy --extra proxy-runtime --extra extra_proxy --extra semantic-router --python python3
COPY --from=source /app/ ./
RUN rm -rf /app/litellm/proxy/_experimental/out
COPY --from=ui /ui/out/ litellm/proxy/_experimental/out/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups --no-editable \
      --extra proxy --extra proxy-runtime --extra extra_proxy --extra semantic-router --python python3 \
    && XDG_CACHE_HOME=/opt/prisma/.cache PRISMA_BINARY_CACHE_DIR=/opt/prisma/binaries \
      prisma generate --schema=./schema.prisma \
    && chmod +x docker/entrypoint.sh docker/prod_entrypoint.sh

FROM base
WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PRISMA_BINARY_CACHE_DIR=/opt/prisma/binaries \
    PRISMA_CLI_PATH=/opt/prisma/binaries/node_modules/.bin/prisma \
    PRISMA_CLI_QUERY_ENGINE_TYPE=binary \
    PRISMA_OFFLINE_MODE=true
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/docker /app/docker
COPY --from=builder /app/schema.prisma /app/schema.prisma
COPY --from=builder /app/litellm/proxy/prisma_migration.py /app/litellm/proxy/prisma_migration.py
COPY --from=builder /opt/prisma /opt/prisma
COPY --from=source /app/LICENSE /app/LICENSE.litellm
COPY LICENSE.patches /app/LICENSE.patches
COPY oidc_delegated_auth.py /app/litellm-config/oidc_delegated_auth.py
COPY verify_oss.py verify_auth.py verify_streaming.py verify_logging.py /tmp/litellm-checks/
RUN chmod -R a+rX /opt/prisma \
    && test -x /opt/prisma/binaries/node_modules/.bin/prisma \
    && test -f /opt/prisma/binaries/node_modules/prisma/build/index.js \
    && python3 -c "from prisma.client import BINARY_PATHS; paths = list(BINARY_PATHS.query_engine.values()); assert paths and all(p.startswith('/opt/prisma/') for p in paths), paths" \
    && python3 /tmp/litellm-checks/verify_oss.py \
    && python3 /tmp/litellm-checks/verify_auth.py \
    && LITELLM_LOCAL_MODEL_COST_MAP=true python3 /tmp/litellm-checks/verify_streaming.py \
    && LITELLM_LOCAL_MODEL_COST_MAP=true python3 /tmp/litellm-checks/verify_logging.py \
    && litellm --help > /dev/null \
    && rm -rf /tmp/litellm-checks
EXPOSE 4000/tcp
ENTRYPOINT ["docker/prod_entrypoint.sh"]
CMD ["--port", "4000"]
