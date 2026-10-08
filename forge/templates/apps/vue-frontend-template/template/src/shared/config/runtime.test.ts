import { describe, expect, it } from 'vitest'
import { appConfig, buildAppConfig } from './runtime'

describe('runtime configuration contract', () => {
  it('uses safe defaults for absent and empty deployment settings', () => {
    expect(buildAppConfig({})).toEqual(appConfig)
    expect(buildAppConfig({ VITE_API_TIMEOUT_MS: ' ', VITE_MAX_TOASTS: null }).api.timeoutMs).toBe(30000)
  })
  it('accepts positive integer overrides', () => {
    const value = buildAppConfig({ VITE_API_TIMEOUT_MS: '1200', VITE_DEFAULT_PAGE_SIZE: '20', VITE_MAX_TOASTS: 3 })
    expect(value.api.timeoutMs).toBe(1200)
    expect(value.pagination.defaultPageSize).toBe(20)
    expect(value.toast.maxConcurrent).toBe(3)
  })
  it.each(['invalid', '-1', '0', '1.5', 'Infinity'])('rejects malformed values with the variable name: %s', value => {
    expect(() => buildAppConfig({ VITE_API_TIMEOUT_MS: value })).toThrow(/VITE_API_TIMEOUT_MS/)
  })
})
