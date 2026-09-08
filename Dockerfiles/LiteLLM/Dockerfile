# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# renovate: datasource=github-tags depName=BerriAI/litellm
ARG IMAGE_VERSION=1.92.0
ARG UPSTREAM_COMMIT=b3086ccd74553565c9a39716e72303ae985555f9

FROM rust:1.90.0-slim-trixie@sha256:7fa728f3678acf5980d5db70960cf8491aff9411976789086676bdf0c19db39e AS rust

FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim@sha256:0b973c14a35cb0dc8fe63a2e8c9919fd797ac566de13090fcf0df4a6b3994b78 AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash openssl tzdata nodejs libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

FROM base AS source
ARG IMAGE_VERSION
ARG UPSTREAM_COMMIT
WORKDIR /app
ADD --checksum=${UPSTREAM_COMMIT} https://github.com/BerriAI/litellm.git#v${IMAGE_VERSION} /app
COPY strip_enterprise.py verify_oss.py base-sources.sha256 litellm-oss.patch litellm-auth.patch /patches/
RUN apt-get update && apt-get install -y --no-install-recommends patch \
    && python3 /patches/strip_enterprise.py /app \
    && sha256sum -c /patches/base-sources.sha256 \
    && patch --batch --forward --fuzz=0 -p1 < /patches/litellm-oss.patch \
    && patch --batch --forward --fuzz=0 -p1 < /patches/litellm-auth.patch \
    && python3 /patches/verify_oss.py /app

FROM --platform=$BUILDPLATFORM node:20.18-alpine3.20@sha256:3488b10bf958af7125a176419d2d8a9937d895bf124012aae811651988d2ffe6 AS ui
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
    && prisma generate --schema=./schema.prisma \
    && chmod +x docker/entrypoint.sh docker/prod_entrypoint.sh

FROM base
WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}"
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/docker /app/docker
COPY --from=builder /app/schema.prisma /app/schema.prisma
COPY --from=builder /app/litellm/proxy/prisma_migration.py /app/litellm/proxy/prisma_migration.py
COPY --from=builder /root/.cache/prisma /root/.cache/prisma
COPY --from=builder /root/.cache/prisma-python /root/.cache/prisma-python
COPY --from=source /app/LICENSE /app/LICENSE.litellm
COPY LICENSE.litellm-oss /app/LICENSE.litellm-oss-patches
COPY oidc_delegated_auth.py /app/litellm-config/oidc_delegated_auth.py
COPY verify_oss.py verify_auth.py /tmp/litellm-checks/
RUN python3 /tmp/litellm-checks/verify_oss.py \
    && python3 /tmp/litellm-checks/verify_auth.py \
    && litellm --help > /dev/null \
    && rm -rf /tmp/litellm-checks
EXPOSE 4000/tcp
ENTRYPOINT ["docker/prod_entrypoint.sh"]
CMD ["--port", "4000"]
