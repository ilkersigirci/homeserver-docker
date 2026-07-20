# Codex ACP

This image runs Marimo's WebSocket-to-stdio bridge around the published
`@agentclientprotocol/codex-acp` adapter. The adapter supplies a compatible
`@openai/codex` dependency and starts Codex App Server. Dependencies are
installed from `package-lock.json`; startup does not invoke `npx` or contact
the npm registry.

The container runs as the upstream Node image's non-root `node` user (UID/GID
1000), uses `/workspace` as its working directory, and reads Codex state from
`/codex-home`.

## Authentication

Run `codex login` before starting the container. Bind the resulting
`auth.json` read-write at `/codex-home/auth.json`; Codex must be able to persist
refreshed credentials. The host file and workspace must be accessible to
UID/GID 1000.

```bash
docker run --rm --init -p 3021:3021 \
  --mount type=bind,src=/path/to/.codex/auth.json,dst=/codex-home/auth.json \
  --mount type=bind,src=/path/to/workspace,dst=/workspace \
  homeserver-codex-acp:test
```

Connect an ACP WebSocket client to `ws://127.0.0.1:3021`. The bridge starts one
stdio `codex-acp` child per WebSocket connection and suppresses protocol payload
logging. Codex uses Bubblewrap for its Linux filesystem sandbox; the host and
container runtime must permit unprivileged user namespaces.

## Compose

`apps/marimo.yml` uses the local `homeserver-codex-acp:test` tag until the
GHCR package is published. It bind-mounts `$CODEX_AUTH_FILE` when set;
otherwise it expects `configs/codex-acp/auth.json`. The file must remain
writable by `PUID:PGID` so Codex can persist refreshed credentials. Its
workspace is the same `$REPO_PATH/data/marimo` bind mounted by Marimo.

The adapter is patched to advertise ChatGPT before API-key authentication
because Marimo 0.23.14 selects the first method. The patch targets the pinned
adapter bundle and intentionally fails the image build when it no longer
applies.

## References

- [Codex ACP](https://github.com/agentclientprotocol/codex-acp)
- [Marimo external agents](https://docs.marimo.io/guides/editor_features/agents/)
- [stdio-to-ws](https://github.com/marimo-team/stdio-to-ws)
- [Codex Linux sandbox](https://github.com/openai/codex/tree/main/codex-rs/linux-sandbox)
