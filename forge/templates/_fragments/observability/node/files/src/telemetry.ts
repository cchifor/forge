/**
 * OpenTelemetry bootstrap for Node services.
 *
 * Imported as a side-effect at the top of src/index.ts (before Fastify
 * constructs) so auto-instrumentations can patch modules before they're
 * loaded. The SDK runs as a no-op when OTEL_EXPORTER_OTLP_ENDPOINT is
 * unset — safe to leave enabled in all environments.
 */

import { NodeSDK } from "@opentelemetry/sdk-node";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";

const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
const serviceName = process.env.OTEL_SERVICE_NAME ?? "forge-service";
const serviceVersion = process.env.OTEL_SERVICE_VERSION ?? "0.1.0";

let sdk: NodeSDK | null = null;

if (endpoint) {
	sdk = new NodeSDK({
		resource: new Resource({
			[ATTR_SERVICE_NAME]: serviceName,
			[ATTR_SERVICE_VERSION]: serviceVersion,
		}),
		traceExporter: new OTLPTraceExporter({ url: `${endpoint.replace(/\/$/, "")}/v1/traces` }),
		instrumentations: [
			getNodeAutoInstrumentations({
				// Disable noisy fs spans — the defaults trace every file read.
				"@opentelemetry/instrumentation-fs": { enabled: false },
			}),
		],
	});
	sdk.start();

	const shutdown = async () => {
		try {
			await sdk?.shutdown();
		} catch (err) {
			// eslint-disable-next-line no-console
			console.warn("otel shutdown failed:", err);
		}
	};
	process.on("SIGTERM", shutdown);
	process.on("SIGINT", shutdown);
	// eslint-disable-next-line no-console
	console.log(`[otel] tracing enabled → ${endpoint} (service=${serviceName})`);
} else {
	// eslint-disable-next-line no-console
	console.log("[otel] OTEL_EXPORTER_OTLP_ENDPOINT unset; tracing disabled");
}

export {};
