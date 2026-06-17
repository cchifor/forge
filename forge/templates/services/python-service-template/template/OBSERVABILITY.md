# Observability

How to get traces, metrics, and structured logs out of this Python/FastAPI
service. See `OPERATIONS.md` for config/migration/shutdown.

## Enabling it

OpenTelemetry and JSON logging are opt-in **forge generation options**:

- `observability.otel` — OTLP traces + RED metrics (FastAPI & HTTPX instrumented).
- `observability.json_logging` — single-line JSON logs with request context.

If this service was generated without them, regenerate with
`--set observability.otel=true --set observability.json_logging=true`
(or run `forge --update` after enabling them in `forge.toml`).

## Environment variables (OTel)

When `observability.otel` is enabled, the app reads:

| Variable | Required | Notes |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | to export | OTLP endpoint, e.g. `http://alloy:4318`. **Unset = spans/metrics are created but discarded** (no crash) — handy for local dev. |
| `OTEL_SERVICE_NAME` | optional | Service name on spans/metrics. |
| `OTEL_RESOURCE_ATTRIBUTES` | optional | e.g. `deployment.environment=prod` (default `deployment.environment=dev`). |

The bundled `docker-compose` fragment points `OTEL_EXPORTER_OTLP_ENDPOINT` at an
`alloy` (OpenTelemetry Collector) service on `:4318`.

## RED metrics

With `observability.otel` on, a metrics middleware records the RED signals per
route and exports them over OTLP:

- **Rate** — `http.server.request.count` (counter; labels: method, route, status).
- **Errors** — the same counter filtered to `status >= 500`.
- **Duration** — `http.server.request.duration` (histogram, milliseconds).
- Plus `http.server.active_requests` (in-flight gauge).

`/health`, `/metrics`, `/docs`, and `/openapi.json` are skipped to keep label
cardinality down.

## Prometheus / Grafana

Metrics flow app → OTLP → Collector → Prometheus. Point your Collector's
Prometheus exporter at Prometheus, then build a RED dashboard:

```promql
# Rate (req/s) by route
sum by (http_route) (rate(http_server_request_count_total[5m]))

# Error rate (%) by route
100 * sum by (http_route) (rate(http_server_request_count_total{http_status_code=~"5.."}[5m]))
        / sum by (http_route) (rate(http_server_request_count_total[5m]))

# p95 latency (ms) by route
histogram_quantile(0.95, sum by (le, http_route) (rate(http_server_request_duration_bucket[5m])))
```

Exact metric names depend on the Collector's Prometheus exporter naming; adjust
to match your pipeline. A three-panel Grafana dashboard (Rate / Errors /
Duration) over these queries gives the standard RED view.

## Structured logs

With `observability.json_logging` on, logs are single-line JSON enriched with
`correlation_id`, request fields (`method`, `path`, `status`, `duration_ms`),
and any tenant/user identifiers in context — ready to ship to Loki/ELK. The
formatter is wired in the logging config (`config/*.yaml`).
