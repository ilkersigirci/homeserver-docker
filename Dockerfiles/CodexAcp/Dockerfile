# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
ARG NODE_VERSION=24.18.0-bookworm-slim

FROM node:${NODE_VERSION}@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS dependencies

WORKDIR /opt/codex-acp

RUN apt-get update \
    && apt-get install --yes --no-install-recommends patch \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json codex-acp-chatgpt-first.patch ./

RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && patch --batch --forward --strip=1 \
      --directory=node_modules/@agentclientprotocol/codex-acp \
      < codex-acp-chatgpt-first.patch

FROM node:${NODE_VERSION}@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d

ENV CODEX_HOME=/codex-home \
    NODE_ENV=production \
    PATH=/opt/codex-acp/node_modules/.bin:$PATH

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
      bubblewrap \
      ca-certificates \
      git \
      ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /codex-home /opt/codex-acp /workspace \
    && chown node:node /codex-home /opt/codex-acp /workspace

COPY --from=dependencies --chown=node:node /opt/codex-acp/node_modules/ /opt/codex-acp/node_modules/
COPY --chmod=0755 healthcheck.mjs /usr/local/bin/codex-acp-healthcheck

USER node:node
WORKDIR /workspace

EXPOSE 3021

HEALTHCHECK --interval=5m --timeout=5s --start-period=15s --start-interval=5s --retries=3 \
  CMD ["/usr/local/bin/codex-acp-healthcheck"]

ENTRYPOINT ["stdio-to-ws"]
CMD ["--quiet", "--port", "3021", "codex-acp"]
