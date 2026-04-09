import ky, { type KyInstance } from 'ky'

let clientInstance: KyInstance | null = null
let tokenGetter: (() => Promise<string | null>) | null = null
let onUnauthorized: (() => void) | null = null

export function configureApiClient(options: {
  getToken: () => Promise<string | null>
  onUnauthorized: () => void
}) {
  tokenGetter = options.getToken
  onUnauthorized = options.onUnauthorized
  clientInstance = null // reset so next getApiClient() creates fresh instance
}

export function getApiClient(): KyInstance {
  if (clientInstance) return clientInstance

  clientInstance = ky.create({
    prefixUrl: import.meta.env.VITE_API_BASE_URL || window.location.origin,
    credentials: 'include',
    hooks: {
      beforeRequest: [
        async (request) => {
          if (tokenGetter) {
            const token = await tokenGetter()
            if (token) {
              request.headers.set('Authorization', `Bearer ${token}`)
            }
          }
        },
      ],
      afterResponse: [
        async (_request, _options, response) => {
          if (response.status === 401 && onUnauthorized) {
            onUnauthorized()
          }
        },
      ],
    },
    timeout: 30_000,
    retry: { limit: 0 }, // Vue Query handles retries
  })

  return clientInstance
}
