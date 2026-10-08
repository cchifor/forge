import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })

it('refreshes a session and retries a mutation with its original body and credentials', async () => {
  const requests: Request[] = []
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(String(input), window.location.origin), init)
    requests.push(request)
    if (request.url.endsWith('/auth/userinfo')) return new Response('{}', { status: 200 })
    return Response.json({ saved: requests.length > 1 }, { status: requests.length === 1 ? 401 : 200 })
  })
  vi.stubGlobal('fetch', fetcher)
  const { configureApiClient, getApiClient } = await import('./client')
  const unauthorized = vi.fn()
  configureApiClient({ getToken: async () => 'token', onUnauthorized: unauthorized })
  const result = await getApiClient().post('api/retry', { json: { name: 'Keep this body' } }).json()
  expect(result).toEqual({ saved: true })
  expect(requests).toHaveLength(3)
  expect(requests[2].headers.get('authorization')).toBe('Bearer token')
  expect(requests[2].credentials).toBe('include')
  expect(await requests[2].json()).toEqual({ name: 'Keep this body' })
  expect(unauthorized).not.toHaveBeenCalled()
})

it('reports expired sessions when refresh fails and preserves the HTTP error', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
  const { configureApiClient, getApiClient } = await import('./client')
  const unauthorized = vi.fn()
  configureApiClient({ getToken: async () => null, onUnauthorized: unauthorized })
  await expect(getApiClient().get('api/private')).rejects.toMatchObject({ response: { status: 401 } })
  expect(unauthorized).toHaveBeenCalledOnce()
})
