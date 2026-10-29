# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# renovate: datasource=github-tags depName=BerriAI/litellm
ARG IMAGE_VERSION=1.106.6
ARG UPSTREAM_COMMIT=955bdaafa8b72b2b6ff728048f272fbc06049f63
# Upstream's in-container PgBouncer (LITELLM_PGBOUNCER_ENABLED), as pinned upstream.
ARG PGBOUNCER_VERSION=1.26.0
ARG PGBOUNCER_SHA256=afd25dd61ee6775d37b40629b87ce08736b3e6955f3057bb212e410fbf21c71d

FROM rust:1.98.0-slim-trixie@sha256:17d1ba895198f9934c6314ec5346a0d5115372f3243390c3d731e242f35c2f27 AS rust

FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim@sha256:0b973c14a35cb0dc8fe63a2e8c9919fd797ac566de13090fcf0df4a6b3994b78 AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash openssl tzdata nodejs libsndfile1 libevent-2.1-7t64 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS pgbouncer-build
ARG PGBOUNCER_VERSION
ARG PGBOUNCER_SHA256
ADD --checksum=sha256:${PGBOUNCER_SHA256} \
    https://www.pgbouncer.org/downloads/files/${PGBOUNCER_VERSION}/pgbouncer-${PGBOUNCER_VERSION}.tar.gz /tmp/pgbouncer.tar.gz
WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libevent-dev libssl-dev \
    && tar xzf /tmp/pgbouncer.tar.gz --strip-components=1 \
    && ./configure --prefix=/usr/local --with-openssl=/usr \
    && make -j"$(nproc)" pgbouncer \
    && install -m 0755 pgbouncer /usr/local/bin/pgbouncer

FROM base AS source
ARG IMAGE_VERSION
ARG UPSTREAM_COMMIT
WORKDIR /app
ADD --checksum=${UPSTREAM_COMMIT} https://github.com/BerriAI/litellm.git#v${IMAGE_VERSION} /app
COPY scripts/strip_enterprise.py tests/verify_oss.py base-sources.sha256 patches/ /patches/
RUN apt-get update && apt-get install -y --no-install-recommends patch \
    && python3 /patches/strip_enterprise.py /app \
    && sha256sum -c /patches/base-sources.sha256 \
    && for p in /patches/permanent/*.patch /patches/temporary/*.patch; do \
        patch --batch --forward --fuzz=0 -p1 < "$p" || exit 1; \
    done \
    && python3 /patches/verify_oss.py /app

FROM --platform=$BUILDPLATFORM node:24.19-alpine3.24@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS ui-build
ENV NEXT_TELEMETRY_DISABLED=1 npm_config_fund=false npm_config_audit=false
WORKDIR /ui
COPY --from=source /app/ui/litellm-dashboard/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --prefer-offline
COPY --from=source /app/ui/litellm-dashboard/ ./
COPY tests/verify_*.integration.test.tsx tests/
RUN npm run test:integration -- tests/verify_ \
    && npm run build

FROM base AS builder
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libssl-dev npm
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup \
    UV_PROJECT_ENVIRONMENT=/app/.venv UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:/usr/local/cargo/bin:${PATH}"
ARG UV_SYNC="uv sync --frozen --no-default-groups --no-editable \
    --extra proxy --extra proxy-runtime --extra extra_proxy --extra semantic-router \
    --extra saml --extra bedrock-realtime --python python3"
COPY --from=source /app/pyproject.toml /app/uv.lock ./
COPY --from=source /app/litellm-proxy-extras/pyproject.toml litellm-proxy-extras/
RUN --mount=type=cache,target=/root/.cache/uv ${UV_SYNC} --no-install-workspace
COPY --from=source /app/ ./
RUN rm -rf /app/litellm/proxy/_experimental/out
COPY --from=ui-build /ui/out/ litellm/proxy/_experimental/out/
# Upstream's uv cache keys omit patched Python sources and the rebuilt dashboard.
RUN --mount=type=cache,target=/root/.cache/uv ${UV_SYNC} --reinstall-package litellm \
    && XDG_CACHE_HOME=/opt/prisma/.cache PRISMA_BINARY_CACHE_DIR=/opt/prisma/binaries \
      prisma generate --schema=./schema.prisma \
    && chmod +x docker/entrypoint.sh docker/prod_entrypoint.sh docker/component_entrypoint.sh

FROM base AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PRISMA_BINARY_CACHE_DIR=/opt/prisma/binaries \
    PRISMA_CLI_PATH=/opt/prisma/binaries/node_modules/.bin/prisma \
    PRISMA_CLI_QUERY_ENGINE_TYPE=binary \
    PRISMA_OFFLINE_MODE=true
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/docker /app/docker
COPY --from=builder /app/gateway /app/gateway
COPY --from=builder /app/backend /app/backend
COPY --from=builder /app/schema.prisma /app/schema.prisma
COPY --from=builder /app/litellm/proxy/prisma_migration.py /app/litellm/proxy/prisma_migration.py
COPY --from=builder /opt/prisma /opt/prisma
COPY --from=pgbouncer-build /usr/local/bin/pgbouncer /usr/local/bin/pgbouncer
COPY --from=source /app/LICENSE /app/LICENSE.litellm
COPY LICENSE.patches /app/LICENSE.patches
COPY src/access_token.py /app/litellm-config/access_token.py
COPY tests/ /tmp/litellm-checks/
RUN chmod -R a+rX /opt/prisma \
    && test -x /opt/prisma/binaries/node_modules/.bin/prisma \
    && test -f /opt/prisma/binaries/node_modules/prisma/build/index.js \
    && python3 -c "from prisma.client import BINARY_PATHS; paths = list(BINARY_PATHS.query_engine.values()); assert paths and all(p.startswith('/opt/prisma/') for p in paths), paths" \
    && for check in /tmp/litellm-checks/verify_*.py; do \
        LITELLM_LOCAL_MODEL_COST_MAP=true python3 "$check" || exit 1; \
    done \
    && python3 -c "import onelogin.saml2.auth, aws_sdk_bedrock_runtime" \
    && pgbouncer --version > /dev/null \
    && litellm --help > /dev/null \
    && rm -rf /tmp/litellm-checks

# Component images replace upstream's litellm-gateway, litellm-backend, and
# litellm-ui images, keeping their ports, default commands, and users.
FROM runtime AS gateway
EXPOSE 4000/tcp
USER 65532:65532
ENTRYPOINT ["sh", "-c", "exec /app/docker/component_entrypoint.sh python -m gateway.launch --workers \"${NUM_WORKERS:-1}\" \"$@\"", "--"]
CMD ["--host", "0.0.0.0", "--port", "4000"]

FROM runtime AS backend
EXPOSE 4001/tcp
USER 65532:65532
ENTRYPOINT ["/app/docker/component_entrypoint.sh", "uvicorn", "backend.main:app"]
CMD ["--host", "0.0.0.0", "--port", "4001"]

FROM nginx:1.31.5-alpine3.24@sha256:34f40471dea485273c5e2a04dd5e97a682332ceb4a9adecd67de450dcb2fb390 AS ui
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --from=ui-build /ui/out /usr/share/nginx/html
COPY --from=source /app/ui/nginx.conf /etc/nginx/nginx.conf
COPY --from=source /app/LICENSE /usr/share/licenses/litellm/LICENSE
COPY LICENSE.patches /usr/share/licenses/litellm/LICENSE.patches
EXPOSE 3000/tcp
CMD ["nginx", "-g", "daemon off;"]

# The unified proxy stays last so it remains the default build target.
FROM runtime AS unified
EXPOSE 4000/tcp
ENTRYPOINT ["docker/prod_entrypoint.sh"]
CMD ["--port", "4000"]
