/**
 * Lightweight telemetry adapter.
 *
 * Provides a single seam so UI surfaces can emit named events without
 * each one knowing whether Sentry, PostHog, or a noop backs the sink
 * today. We expose:
 *
 *   - `useTelemetry()` — the composable returning `{ track }`. Safe to
 *     call before any sink is configured; emits go to the noop default.
 *   - `configureTelemetry(sink)` — installs a sink at boot. Called once
 *     from `app/main.ts` after Sentry initializes.
 *   - `createSentryTelemetrySink()` — a Sentry-backed sink that composes
 *     `reportMessage` (the SDK we ship today has no breadcrumb API).
 *
 * Design constraints:
 *   - Telemetry must never throw. A broken sink should never reach the UI.
 *   - The Sentry import is lazy so the test environment (and any caller
 *     that mocks `./sentry`) doesn't pay for it.
 */

export type EventName = string

export type EventProps = Record<string, string | number | boolean | undefined>

export interface TelemetrySink {
  track(event: EventName, props?: EventProps): void
}

const noopSink: TelemetrySink = { track: () => {} }

let activeSink: TelemetrySink = noopSink

/**
 * Install a sink. Subsequent `track()` calls route through it.
 * Calling again replaces the previous sink; pass `null` to reset to noop.
 */
export function configureTelemetry(sink: TelemetrySink | null): void {
  activeSink = sink ?? noopSink
}

/**
 * Composable returning the telemetry surface. Safe to call anywhere —
 * the underlying sink is resolved at emit time, so callers grab the
 * function once and don't have to re-acquire it after `configureTelemetry`.
 */
export function useTelemetry(): { track: (event: EventName, props?: EventProps) => void } {
  return {
    track: (event, props) => {
      try {
        activeSink.track(event, props)
      } catch {
        /* swallow — telemetry must never break the app */
      }
    },
  }
}

/**
 * Sentry-backed sink. Composes `reportMessage` from `./sentry` because
 * the current SDK surface doesn't expose breadcrumbs.
 *
 * The Sentry module is loaded eagerly via a static ESM import so Vitest
 * `vi.mock('./sentry')` interception works without extra hoisting in
 * call-site tests. The sink is still side-effect-free at module-load:
 * `reportMessage` is a no-op when the SDK isn't initialized.
 */
import { reportMessage } from './sentry'

export function createSentryTelemetrySink(): TelemetrySink {
  return {
    track(event, props) {
      try {
        reportMessage(`telemetry:${event}`, 'info')
        // Forward the props payload as a second message line so it
        // survives the SDK's stringification regardless of integration
        // shape. Skip the extra emit when there are no props.
        if (props && Object.keys(props).length > 0) {
          reportMessage(
            `telemetry:${event}:props ${JSON.stringify(props)}`,
            'info',
          )
        }
      } catch {
        /* swallow — telemetry must never break the app */
      }
    },
  }
}
