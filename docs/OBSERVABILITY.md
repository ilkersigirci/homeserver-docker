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
