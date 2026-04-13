import { describe, it, expect, beforeEach, vi } from 'vitest'
import { configureApiClient, getApiClient } from '@/shared/api/client'

// Reset module state between tests by re-importing fresh module
let freshModule: typeof import('@/shared/api/client')

beforeEach(async () => {
  vi.resetModules()
  freshModule = await import('@/shared/api/client')
})

describe('configureApiClient', () => {
  it('stores configuration without throwing', () => {
    expect(() =>
      freshModule.configureApiClient({
        getToken: async () => 'test-token',
        onUnauthorized: () => {},
      }),
    ).not.toThrow()
  })

  it('resets singleton so next getApiClient creates fresh instance', () => {
    freshModule.configureApiClient({
      getToken: async () => null,
      onUnauthorized: () => {},
    })
    const first = freshModule.getApiClient()

    freshModule.configureApiClient({
      getToken: async () => 'new-token',
      onUnauthorized: () => {},
    })
    const second = freshModule.getApiClient()

    expect(first).not.toBe(second)
  })
})

describe('getApiClient', () => {
  it('returns a ky instance after configuration', () => {
    freshModule.configureApiClient({
      getToken: async () => null,
      onUnauthorized: () => {},
    })
    const client = freshModule.getApiClient()
    expect(client).toBeDefined()
    expect(typeof client.get).toBe('function')
    expect(typeof client.post).toBe('function')
  })

  it('returns the same instance on repeated calls', () => {
    freshModule.configureApiClient({
      getToken: async () => null,
      onUnauthorized: () => {},
    })
    const first = freshModule.getApiClient()
    const second = freshModule.getApiClient()
    expect(first).toBe(second)
  })

  it('returns a client even without prior configuration', () => {
    // getApiClient creates a ky instance regardless; tokenGetter is simply null
    const client = freshModule.getApiClient()
    expect(client).toBeDefined()
    expect(typeof client.get).toBe('function')
  })

  it('creates client with expected HTTP methods', () => {
    freshModule.configureApiClient({
      getToken: async () => null,
      onUnauthorized: () => {},
    })
    const client = freshModule.getApiClient()
    expect(typeof client.get).toBe('function')
    expect(typeof client.post).toBe('function')
    expect(typeof client.put).toBe('function')
    expect(typeof client.delete).toBe('function')
    expect(typeof client.patch).toBe('function')
  })
})
