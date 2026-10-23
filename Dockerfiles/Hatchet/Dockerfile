# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
# renovate: datasource=github-releases depName=hatchet-dev/hatchet
ARG IMAGE_VERSION=v0.110.5
ARG UPSTREAM_COMMIT=56c617e0da399bc9d8a10d2ba74b4950f8a950b8

FROM golang:1.26.10-alpine@sha256:27f2d3b83cfc5803c8078f8e730af0f7c431bf067afaec8f60a36fb763187cba AS server-build

ARG IMAGE_VERSION
ARG UPSTREAM_COMMIT
WORKDIR /src
ENV CGO_ENABLED=0

# Pin the official release source by tag and commit so builds are reproducible.
ADD --checksum=${UPSTREAM_COMMIT} https://github.com/hatchet-dev/hatchet.git#${IMAGE_VERSION} .

COPY base-sources.sha256 oidc.patch /patches/
RUN apk add --no-cache git patch python3 \
    && sha256sum -c /patches/base-sources.sha256 \
    && patch --batch --forward --fuzz=0 -p1 < /patches/oidc.patch \
    && (cd frontend/snippets && python3 -X utf8 generate.py)

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    go test \
      ./api/v1/server/handlers/users \
      ./api/v1/server/authn \
      -run 'OIDC|OAuth|Session' -count=1 \
    && go build -ldflags="-w -s -X 'main.Version=${IMAGE_VERSION}'" \
      -o /out/hatchet-lite ./cmd/hatchet-lite \
    && go build -ldflags="-w -s -X 'main.Version=${IMAGE_VERSION}'" \
      -o /out/hatchet-migrate ./cmd/hatchet-migrate \
    && go build -ldflags="-w -s -X 'github.com/hatchet-dev/hatchet/cmd/hatchet-admin/cli.Version=${IMAGE_VERSION}'" \
      -o /out/hatchet-admin ./cmd/hatchet-admin

FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend-build

WORKDIR /app

COPY --from=server-build /src/frontend/app/package.json /src/frontend/app/pnpm-lock.yaml ./
RUN corepack pnpm@10.16.1 install --frozen-lockfile \
    && corepack pnpm@10.16.1 store prune

COPY --from=server-build /src/frontend/app/ ./
RUN npm run build

# Split images replace only the patched upstream hatchet-api and
# hatchet-frontend images, keeping their layout and default commands.
FROM server-build AS api-build

ARG IMAGE_VERSION
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    go build -ldflags="-w -s -X 'main.Version=${IMAGE_VERSION}'" \
      -o /out/hatchet-api ./cmd/hatchet-api

FROM server-build AS staticfileserver-build

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    go build -ldflags="-w -s" \
      -o /out/hatchet-staticfileserver ./cmd/hatchet-staticfileserver

FROM alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS api

WORKDIR /hatchet
RUN apk add --no-cache bash ca-certificates openssl tzdata
COPY --from=api-build /out/hatchet-api ./

EXPOSE 8080

CMD ["/hatchet/hatchet-api"]

FROM alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS frontend

WORKDIR /app
COPY --from=frontend-build /app/dist ./dist
COPY --from=staticfileserver-build /out/hatchet-staticfileserver ./

EXPOSE 80

CMD ["/app/hatchet-staticfileserver", "-static-asset-dir", "/app/dist"]

# Hatchet Lite stays last so it remains the default build target.
FROM alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS lite

ARG IMAGE_VERSION
ARG UPSTREAM_COMMIT
LABEL org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${UPSTREAM_COMMIT}" \
      org.opencontainers.image.source="https://github.com/hatchet-dev/hatchet"

RUN apk add --no-cache bash ca-certificates curl openssl postgresql-client tzdata

COPY --from=server-build /out/hatchet-* /
COPY --from=server-build --chmod=0755 /src/hack/lite/start.sh /entrypoint.sh
COPY --from=frontend-build /app/dist /static-assets

ENV LITE_STATIC_ASSET_DIR=/static-assets \
    LITE_FRONTEND_PORT=8081 \
    LITE_RUNTIME_PORT=8888

EXPOSE 8888 7070

CMD ["./entrypoint.sh"]
