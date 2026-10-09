import { afterEach, expect, it, vi } from 'vitest'
import { initSentry, reportError, reportMessage } from './sentry'
afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })
it('keeps an unconfigured application usable and reports local errors for development', async () => {
  vi.stubEnv('VITE_SENTRY_DSN', '')
  const app = {} as Parameters<typeof initSentry>[0]
  const router = {} as Parameters<typeof initSentry>[1]
  await initSentry(app, router)
  const error = new Error('local failure')
  const log = vi.spyOn(console, 'error').mockImplementation(() => {})
  reportError(error, { component: 'editor' })
  expect(log).toHaveBeenCalledWith('[reportError]', error, { component: 'editor' })
  expect(() => reportMessage('ready')).not.toThrow()
})
it('does not block startup if an optional telemetry SDK is missing', async () => {
  vi.stubEnv('VITE_SENTRY_DSN', 'https://key@example.invalid/1')
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  await initSentry({} as Parameters<typeof initSentry>[0], {} as Parameters<typeof initSentry>[1])
  expect(warn).toHaveBeenCalledWith(expect.stringContaining('not installed'))
})
