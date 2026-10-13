# Observability and OpenTelemetry

This document describes the OpenTelemetry pattern used in this repository.

## Intent

- Use a local agent per host for telemetry collection.
- Keep service instrumentation consistent across stacks.
- Forward telemetry to central backends.

## Topology

- Run `apps/grafana-lgtm.yml` on the `gpu` machine.
- Run `apps/otel-collector-agent.yml` on every machine.
- Instrumented services send OTLP to the local `otel-collector-agent`.

## LGTM Readiness

The container healthcheck covers Grafana, Loki, Tempo, Pyroscope, Prometheus, and
the collector. A failure in any backend makes the whole container unhealthy.
Check individual endpoints from `apps/grafana-lgtm.yml` with `docker exec` to
identify the failing backend.

Pyroscope's single-node metastore uses `metastore.raft.log_store_timeout: 0s` in
`configs/grafana-lgtm/pyroscope/default.yaml`. This disables the asynchronous
write-timeout wrapper that can leave Pyroscope 2.3.1 stuck with `non-monotonic log
entries` after a disk stall. Disk writes wait for completion; a persistent disk
stall will still fail readiness. Keep this setting until the bundled Pyroscope
includes the [Raft write reconciliation fix](https://github.com/grafana/pyroscope/pull/5307)
(released in Pyroscope 2.4.0).

If this failure has already occurred, restart `grafana-lgtm` after applying the
configuration. Preserve `/data/pyroscope/metastore` and its WAL and snapshots;
restarting replays the existing state without resetting profile storage.

## Standard OTLP Environment

Use this in telemetry-enabled services:

```env
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector-agent:4317
OTEL_EXPORTER_OTLP_INSECURE=true
```

## Host Metrics Responsibility

The per-host collector agent is expected to export host metrics including:

- `cpu`
- `memory`
- `disk`
- `filesystem`
- `network`

## Service Onboarding Checklist

- Add OTLP environment variables to the service.
- Ensure `otel-collector-agent` is included on that host.
- Verify telemetry appears in the configured backend dashboards/logs/traces.
