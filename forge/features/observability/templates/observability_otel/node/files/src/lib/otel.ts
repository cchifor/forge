/**
 * OpenTelemetry setup for Node/Fastify backends.
 *
 * Initialises tracer + metrics providers wired to the OTLP gRPC
 * exporter, with the ``@opentelemetry/instrumentation-fastify`` +
 * ``@opentelemetry/instrumentation-http`` instrumentations enabled.
 *
 * Env:
 *   OTEL_EXPORTER_OTLP_ENDPOINT = http://otel-collector:4317
 *   OTEL_SERVICE_NAME           = project-backend
 */
import { NodeSDK } from '@opentelemetry/sdk-node'
import { Resource } from '@opentelemetry/resources'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc'
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'

let sdk: NodeSDK | null = null

export function configureOtel(serviceName: string): void {
  const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT
  if (!endpoint) return

  sdk = new NodeSDK({
    resource: new Resource({ 'service.name': serviceName }),
    traceExporter: new OTLPTraceExporter({ url: endpoint }),
    instrumentations: [getNodeAutoInstrumentations()],
  })
  sdk.start()
}

export async function shutdownOtel(): Promise<void> {
  if (sdk) {
    await sdk.shutdown()
    sdk = null
  }
}
