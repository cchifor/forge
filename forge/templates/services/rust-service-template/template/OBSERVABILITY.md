# Observability

How to get traces, metrics, and logs out of this Rust/Axum service. See
`OPERATIONS.md` for config/migration/shutdown.

## Logs (always on)

The service uses the `tracing` crate with a subscriber that emits structured
events to stdout. Set the level with the standard `RUST_LOG` env var, e.g.
`RUST_LOG=info` (or `RUST_LOG=my_service=debug,tower_http=info`). In a container
these lines are picked up by your log shipper (Loki/ELK) directly.

## Tracing / metrics (OTel)

OpenTelemetry is an opt-in **forge generation option**, `observability.otel`.
If this service was generated without it, regenerate with
`--set observability.otel=true` (or enable it in `forge.toml` and run
`forge --update`).

When enabled, the service initializes OTLP export and reads:

| Variable | Required | Notes |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | to export | OTLP endpoint, e.g. `http://alloy:4318`. **Unset = no OTLP layer is registered** — spans are not exported. The tracing subscriber still logs structured events to stdout. |
| `OTEL_SERVICE_NAME` | optional | Service name on spans. |

The bundled `docker-compose` fragment points `OTEL_EXPORTER_OTLP_ENDPOINT` at an
`alloy` (OpenTelemetry Collector) service on `:4318`.

## Prometheus / Grafana (RED)

Metrics flow app → OTLP → Collector → Prometheus. With the Collector's
Prometheus exporter feeding Prometheus, build a RED dashboard over the HTTP
server metrics:

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
