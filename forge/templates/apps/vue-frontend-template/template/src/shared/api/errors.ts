import { HTTPError } from 'ky'

export interface ApiErrorInfo {
  message: string
  type?: string
  status?: number
  detail?: Record<string, unknown>
}

/**
 * Normalize any thrown error into a structured shape suitable for a toast,
 * banner, or inline surface. Reads the platform envelope first:
 *   `{ message: string, type: string, detail: { code: number } }`
 * Falls back to legacy FastAPI shapes:
 *   `{ detail: string }` or `{ detail: [{loc, msg, ...}, ...] }`
 *
 * Never returns raw response bodies — long upstream HTTP-headers dumps must
 * not bleed into UI strings. Unrecognized bodies yield a generic
 * "Request failed (<status>)" message instead.
 */
export async function unpackApiError(err: unknown): Promise<ApiErrorInfo> {
  if (err instanceof HTTPError) {
    const status = err.response.status
    let parsed: Record<string, unknown> | null = null
    try {
      parsed = (await err.response.clone().json()) as Record<string, unknown>
    } catch {
      parsed = null
    }
    if (parsed && typeof parsed === 'object') {
      const message = extractDetailMessage(parsed)
      if (message) {
        return {
          message,
          type: typeof parsed.type === 'string' ? parsed.type : undefined,
          status,
          detail:
            parsed.detail && typeof parsed.detail === 'object'
              ? (parsed.detail as Record<string, unknown>)
              : undefined,
        }
      }
    }
    const statusText = err.response.statusText || ''
    return {
      message: `Request failed (${status}${statusText ? ` ${statusText}` : ''}).`,
      status,
    }
  }
  if (err instanceof Error) return { message: err.message }
  return { message: String(err) }
}

/**
 * Legacy thin wrapper for existing call sites that only need a string.
 * Prefer `unpackApiError` for new code that can use `type`/`status`.
 */
export async function unpackApiErrorMessage(err: unknown): Promise<string> {
  const info = await unpackApiError(err)
  return info.message
}

/**
 * Synchronous fallback — useful inside non-async contexts where the caller
 * already has a parsed body.
 */
export function formatDetail(body: unknown): string | null {
  return extractDetailMessage(body)
}

function extractDetailMessage(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const obj = body as Record<string, unknown>

  // Platform envelope: { message, type, detail: { code } }
  if (typeof obj.message === 'string' && obj.message.trim().length > 0) {
    return obj.message
  }

  // Legacy FastAPI envelope: { detail: string | ValidationError[] }
  const detail = obj.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts: string[] = []
    for (const entry of detail) {
      if (!entry || typeof entry !== 'object') continue
      const e = entry as Record<string, unknown>
      const loc = Array.isArray(e.loc) ? e.loc : []
      const field = loc.length ? String(loc[loc.length - 1]) : ''
      const msg = typeof e.msg === 'string' ? e.msg : 'invalid'
      parts.push(field ? `${field}: ${msg}` : msg)
    }
    if (parts.length) return parts.join(' · ')
  }
  return null
}
