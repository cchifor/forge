/**
 * Sentry bootstrap — browser error + performance tracking.
 *
 * Design notes:
 *  - The Sentry SDK is imported dynamically. If `@sentry/vue` is not installed
 *    (or the import fails), we log a warning and let the app boot normally.
 *    That keeps `npm install` optional for the SDK until someone wants
 *    production telemetry.
 *  - VITE_SENTRY_DSN is the ONLY required config. Empty = disabled (no init).
 *  - `traceparent` propagation is configured so a browser span links to the
 *    backend trace emitted by the gatekeeper / deepagent OTEL pipeline.
 *    The `tracePropagationTargets` list must include every origin the frontend
 *    calls; right now that's just same-origin (`/api/*`, `/agent/*`).
 *
 * To enable in production:
 *    1. `npm install --save @sentry/vue`
 *    2. Set VITE_SENTRY_DSN in your build env
 *    3. (Optional) set VITE_SENTRY_ENVIRONMENT, VITE_SENTRY_RELEASE,
 *       VITE_SENTRY_TRACES_SAMPLE_RATE
 */

import type { App } from 'vue'
import type { Router } from 'vue-router'

type SentryModule = {
  init: (opts: Record<string, unknown>) => void
  captureException: (err: unknown, hint?: Record<string, unknown>) => void
  captureMessage: (msg: string, level?: string) => void
  browserTracingIntegration?: (opts?: Record<string, unknown>) => unknown
  replayIntegration?: (opts?: Record<string, unknown>) => unknown
  [key: string]: unknown
}

let _sentry: SentryModule | null = null

export async function initSentry(app: App, router: Router): Promise<void> {
  const dsn = import.meta.env.VITE_SENTRY_DSN
  if (!dsn) return

  try {
    // Dynamic import keeps bundler optional; types stay minimal.
    _sentry = (await import(/* @vite-ignore */ '@sentry/vue')) as unknown as SentryModule
  } catch {
    // SDK not installed — don't block app boot; log once so the dev knows.
    console.warn(
      '[sentry] VITE_SENTRY_DSN is set but @sentry/vue is not installed. ' +
        'Run `npm install @sentry/vue` to enable error tracking.',
    )
    return
  }

  const integrations: unknown[] = []
  if (typeof _sentry.browserTracingIntegration === 'function') {
    integrations.push(
      _sentry.browserTracingIntegration({
        router,
        // Propagate W3C traceparent to same-origin API/agent requests so the
        // browser span connects to the backend trace.
        tracePropagationTargets: [
          /^\/api\//,
          /^\/agent\//,
          window.location.origin,
        ],
      }),
    )
  }
  if (typeof _sentry.replayIntegration === 'function') {
    integrations.push(_sentry.replayIntegration())
  }

  _sentry.init({
    app,
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT ?? import.meta.env.MODE,
    release: import.meta.env.VITE_SENTRY_RELEASE,
    tracesSampleRate: Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? '0.1'),
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 1.0,
    integrations,
  })
}

/**
 * Report an error. Safe to call before initSentry completes — becomes a no-op
 * when Sentry isn't configured, so callers don't need to guard the call site.
 */
export function reportError(err: unknown, context?: Record<string, unknown>): void {
  if (_sentry) {
    _sentry.captureException(err, context ? { contexts: { custom: context } } : undefined)
  } else if (import.meta.env.DEV) {
    // In dev without Sentry, surface the error to the console with its context.
    console.error('[reportError]', err, context)
  }
}

export function reportMessage(msg: string, level: 'info' | 'warning' | 'error' = 'info'): void {
  if (_sentry) {
    _sentry.captureMessage(msg, level)
  }
}
