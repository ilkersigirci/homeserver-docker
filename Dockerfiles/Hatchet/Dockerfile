# syntax=docker/dockerfile:1.26@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
# renovate: datasource=github-tags depName=hatchet-dev/hatchet
ARG IMAGE_VERSION=v0.107.0
ARG UPSTREAM_COMMIT=22e6fc995227011818c676e04a97ff535fb73887

FROM golang:1.26-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS server-build

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
    go test ./api/v1/server/handlers/users -run 'OIDC' -count=1 \
    && go build -ldflags="-w -s -X 'main.Version=${IMAGE_VERSION}'" \
      -o /out/ \
      ./cmd/hatchet-lite \
      ./cmd/hatchet-admin \
      ./cmd/hatchet-migrate

FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS frontend-build

WORKDIR /app

COPY --from=server-build /src/frontend/app/package.json /src/frontend/app/pnpm-lock.yaml ./
RUN corepack pnpm@10.16.1 install --frozen-lockfile \
    && corepack pnpm@10.16.1 store prune

COPY --from=server-build /src/frontend/app/ ./
RUN npm run build

FROM alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

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
