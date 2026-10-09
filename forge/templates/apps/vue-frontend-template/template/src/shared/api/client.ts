import ky, { type KyInstance } from 'ky'

let clientInstance: KyInstance | null = null
let tokenGetter: (() => Promise<string | null>) | null = null
let onUnauthorized: (() => void) | null = null

let refreshInFlight: Promise<boolean> | null = null

async function silentRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight
  refreshInFlight = (async () => {
    try {
      const res = await fetch('/auth/userinfo', { credentials: 'include' })
      return res.ok
    } catch {
      return false
    } finally {
      queueMicrotask(() => {
        refreshInFlight = null
      })
    }
  })()
  return refreshInFlight
}

async function captureBody(request: Request): Promise<ArrayBuffer | undefined> {
  if (request.method === 'GET' || request.method === 'HEAD') return undefined
  if (!request.body) return undefined
  try {
    return await request.clone().arrayBuffer()
  } catch {
    return undefined
  }
}

export function configureApiClient(options: {
  getToken: () => Promise<string | null>
  onUnauthorized: () => void
}) {
  tokenGetter = options.getToken
  onUnauthorized = options.onUnauthorized
  clientInstance = null
}

export function getApiClient(): KyInstance {
  if (clientInstance) return clientInstance

  clientInstance = ky.create({
    prefix: import.meta.env.VITE_API_BASE_URL || window.location.origin,
    credentials: 'include',
    timeout: 30_000,
    retry: { limit: 0 },
    hooks: {
      beforeRequest: [
        async ({ request }) => {
          if (tokenGetter) {
            const token = await tokenGetter()
            if (token) {
              request.headers.set('Authorization', `Bearer ${token}`)
            }
          }
        },
      ],
      afterResponse: [
        async ({ request, response }) => {
          if (response.status !== 401) return response

          const refreshed = await silentRefresh()
          if (!refreshed) {
            onUnauthorized?.()
            return response
          }

          try {
            // Ky passes a retained Request clone to afterResponse. Object
            // identity differs from beforeRequest, so read this clone directly.
            const body = await captureBody(request)
            if (request.body && body === undefined) return response
            const retryResp = await fetch(request.url, {
              method: request.method,
              headers: request.headers,
              credentials: 'include',
              ...(body !== undefined ? { body } : {}),
            })
            return retryResp
          } catch {
            onUnauthorized?.()
            return response
          }
        },
      ],
    },
  })

  return clientInstance
}
