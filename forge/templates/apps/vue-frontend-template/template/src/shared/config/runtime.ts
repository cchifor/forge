/**
 * Centralized runtime configuration.
 *
 * Reads ``VITE_*`` env vars once at module load, validates them with
 * Zod, and exports a typed ``appConfig`` singleton consumed across the
 * app. Defaults preserve current behavior — nothing changes unless an
 * operator opts in via ``.env`` / ``.env.local`` / Docker env.
 *
 * On schema failure (non-numeric where number expected, etc.) we throw
 * with a message naming the failing var so the developer / SRE can fix
 * it before the SPA mounts. Every var is optional — missing / empty
 * drops to the in-code default; we throw only on present-but-malformed
 * input.
 */
import { z } from 'zod'

// ── Coercion helpers ─────────────────────────────────────────────────
//
// Zod's ``.default()`` is the outermost wrapper, so it only fires on
// strict ``undefined`` input. A ``.env`` line with no value (``KEY=``)
// supplies an empty string, which would otherwise bypass the default
// and hit the inner schema as ``""``. Each helper below coerces empty
// to undefined inside the preprocess step before validation runs, and
// returns the fallback explicitly when the result is undefined — this
// avoids relying on ``.default()`` chained after ``.transform()``, which
// in Zod v3 feeds the default back through the inner schema rather
// than emitting it directly.

function isMissing(value: unknown): boolean {
  return value === undefined || value === null
    || (typeof value === 'string' && value.trim() === '')
}

/** Positive integer env var. Missing / empty → fallback. */
function positiveIntEnv(label: string, fallback: number) {
  return z
    .unknown()
    .transform((raw, ctx) => {
      if (isMissing(raw)) return fallback
      const n = Number(raw)
      if (!Number.isFinite(n)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `${label} must be a number (got ${JSON.stringify(raw)})`,
        })
        return z.NEVER
      }
      if (!Number.isInteger(n)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `${label} must be an integer (got ${JSON.stringify(raw)})`,
        })
        return z.NEVER
      }
      if (n <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `${label} must be positive (got ${n})`,
        })
        return z.NEVER
      }
      return n
    })
}

/** Non-empty string env var. Missing / empty → fallback. */
function stringEnv(label: string, fallback: string) {
  return z.unknown().transform((raw, ctx) => {
    if (isMissing(raw)) return fallback
    if (typeof raw !== 'string') {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `${label} must be a string (got ${typeof raw})`,
      })
      return z.NEVER
    }
    return raw
  })
}

// ── Defaults ─────────────────────────────────────────────────────────

const DEFAULTS = {
  api: { timeoutMs: 30_000 },
  pagination: { defaultPageSize: 50 },
  cache: { staleTimeDefaultMs: 30_000 },
  toast: { maxConcurrent: 5, durationSuccessMs: 5_000, durationErrorMs: 8_000 },
} as const

// ── Schema ───────────────────────────────────────────────────────────

const schema = z.object({
  VITE_API_TIMEOUT_MS: positiveIntEnv(
    'VITE_API_TIMEOUT_MS',
    DEFAULTS.api.timeoutMs,
  ),
  VITE_DEFAULT_PAGE_SIZE: positiveIntEnv(
    'VITE_DEFAULT_PAGE_SIZE',
    DEFAULTS.pagination.defaultPageSize,
  ),
  VITE_CACHE_STALE_DEFAULT_MS: positiveIntEnv(
    'VITE_CACHE_STALE_DEFAULT_MS',
    DEFAULTS.cache.staleTimeDefaultMs,
  ),
  VITE_MAX_TOASTS: positiveIntEnv('VITE_MAX_TOASTS', DEFAULTS.toast.maxConcurrent),
  VITE_TOAST_DURATION_SUCCESS_MS: positiveIntEnv(
    'VITE_TOAST_DURATION_SUCCESS_MS',
    DEFAULTS.toast.durationSuccessMs,
  ),
  VITE_TOAST_DURATION_ERROR_MS: positiveIntEnv(
    'VITE_TOAST_DURATION_ERROR_MS',
    DEFAULTS.toast.durationErrorMs,
  ),
})

export interface AppConfig {
  api: { timeoutMs: number }
  pagination: { defaultPageSize: number }
  cache: { staleTimeDefaultMs: number }
  toast: { maxConcurrent: number; durationSuccessMs: number; durationErrorMs: number }
}

/**
 * Build the typed config from a raw env-like record. Exported for unit
 * tests so they can drive the schema with arbitrary inputs without
 * touching ``import.meta.env``.
 *
 * Throws ``Error`` with a message naming every failing var when the
 * schema rejects. Production behavior: the singleton below propagates
 * the throw so the SPA fails fast at boot rather than silently
 * mis-tuning.
 */
export function buildAppConfig(source: Record<string, unknown>): AppConfig {
  const result = schema.safeParse(source)
  if (!result.success) {
    const lines = result.error.errors.map((e) => {
      const path = e.path.join('.') || '<root>'
      return `  - ${path}: ${e.message}`
    })
    throw new Error(
      `Invalid webapp runtime config — fix the following VITE_* env vars:\n${lines.join(
        '\n',
      )}`,
    )
  }
  const v = result.data
  return {
    api: {
      timeoutMs: v.VITE_API_TIMEOUT_MS,
    },
    pagination: {
      defaultPageSize: v.VITE_DEFAULT_PAGE_SIZE,
    },
    cache: {
      staleTimeDefaultMs: v.VITE_CACHE_STALE_DEFAULT_MS,
    },
    toast: {
      maxConcurrent: v.VITE_MAX_TOASTS,
      durationSuccessMs: v.VITE_TOAST_DURATION_SUCCESS_MS,
      durationErrorMs: v.VITE_TOAST_DURATION_ERROR_MS,
    },
  }
}

/** Read the raw ``import.meta.env`` once. Wrapped so tests can stub it
 *  without touching the global. */
function readEnv(): Record<string, unknown> {
  try {
    return (import.meta as any).env ?? {}
  } catch {
    return {}
  }
}

/**
 * Process-lifetime singleton. The first import resolves the schema; all
 * subsequent reads return the same object. Throws at module-load if any
 * value is malformed (clear, opt-in failure — the boot logs surface the
 * offending var name).
 */
export const appConfig: AppConfig = buildAppConfig(readEnv())
