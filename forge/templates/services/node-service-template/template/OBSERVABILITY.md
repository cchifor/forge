# Observability

How to get traces, metrics, and logs out of this Node/Fastify service. See
`OPERATIONS.md` for config/migration/shutdown.

## Enabling it

OpenTelemetry is an opt-in **forge generation option**, `observability.otel`.
If this service was generated without it, regenerate with
`--set observability.otel=true` (or enable it in `forge.toml` and run
`forge --update`).

## Environment variables (OTel)

| Variable | Required | Notes |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | to export | OTLP endpoint, e.g. `http://alloy:4318`. **Unset = the OTel SDK is not started** (no overhead, no export) — fine for local dev. |
| `OTEL_SERVICE_NAME` | optional | Service name on spans/metrics. |

The bundled `docker-compose` fragment points `OTEL_EXPORTER_OTLP_ENDPOINT` at an
`alloy` (OpenTelemetry Collector) service on `:4318`.

## What gets instrumented

When the endpoint is set, the app starts the Node SDK with
`@opentelemetry/auto-instrumentations-node` — HTTP, Fastify, and database calls
are traced automatically and exported over OTLP. RED metrics (request rate,
errors, duration) come from the HTTP/Fastify auto-instrumentation's server
metrics.

## Prometheus / Grafana

Metrics flow app → OTLP → Collector → Prometheus. With the Collector's
Prometheus exporter feeding Prometheus, build a RED dashboard:

```promql
# Rate (req/s)
sum by (http_route) (rate(http_server_duration_count[5m]))

# Error rate (%)
100 * sum by (http_route) (rate(http_server_duration_count{http_status_code=~"5.."}[5m]))
        / sum by (http_route) (rate(http_server_duration_count[5m]))

# p95 latency (ms)
histogram_quantile(0.95, sum by (le, http_route) (rate(http_server_duration_bucket[5m])))
```

Metric names follow the OTel HTTP server conventions exported by your Collector;
adjust to match your pipeline. A three-panel Grafana dashboard (Rate / Errors /
Duration) over these gives the standard RED view.

## Logs

Fastify's logger emits structured JSON by default (one object per line with
level, time, request id), ready to ship to Loki/ELK without extra setup.
