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

## LGTM Retention

- Metrics, logs, traces, and profiles all have a 30-day retention policy.
- Prometheus and Loki retention periods are set in `apps/grafana-lgtm.yml`;
  Tempo retention is set in `configs/grafana-lgtm/tempo/default.yaml`, and Pyroscope
  retention for both v1 and v2 storage is set in
  `configs/grafana-lgtm/pyroscope/default.yaml`.
- Loki requires `compactor.retention_enabled` and
  `compactor.delete_request_store: filesystem` to delete expired logs. Preserve
  `/data/loki/compactor`, which holds pending deletion markers.
- Cleanup is asynchronous: Prometheus removes expired whole blocks, and Loki
  deletes marked chunks after its default two-hour delay.

## LGTM Readiness

The container healthcheck covers Grafana, Loki, Tempo, Pyroscope, Prometheus, and
the collector. A failure in any backend makes the whole container unhealthy.
Check individual endpoints from `apps/grafana-lgtm.yml` with `docker exec` to
identify the failing backend.

Preserve `/data/pyroscope/metastore` and its WAL and snapshots across restarts;
Pyroscope replays the existing state without resetting profile storage.

## Standard OTLP Environment

Use this in telemetry-enabled services:

```env
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector-agent:4317
OTEL_EXPORTER_OTLP_INSECURE=true
```

Services outside `t3_proxy` use `http://<host LOCAL_STATIC_IP>:4317` (or `:4318` for HTTP).

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
- Traefik tracing is opt-in. If the service's requests join application traces,
  set `traefik.http.routers.<router>.observability.tracing: "true"`.
- Verify telemetry appears in the configured backend dashboards/logs/traces.
