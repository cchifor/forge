import { afterEach, expect, it, vi } from 'vitest'
import { configureTelemetry, createSentryTelemetrySink, useTelemetry } from './telemetry'
import { reportMessage } from './sentry'
vi.mock('./sentry', () => ({ reportMessage: vi.fn() }))
afterEach(() => { configureTelemetry(null); vi.clearAllMocks() })
it('dispatches events to the current sink without letting failures break the caller', () => {
  const { track } = useTelemetry()
  track('before-config')
  const sink = { track: vi.fn() }
  configureTelemetry(sink)
  track('clicked', { count: 2 })
  expect(sink.track).toHaveBeenCalledWith('clicked', { count: 2 })
  configureTelemetry({ track() { throw new Error('offline') } })
  expect(() => track('offline')).not.toThrow()
  configureTelemetry(createSentryTelemetrySink())
  track('saved', { count: 1 })
  expect(reportMessage).toHaveBeenCalledWith('telemetry:saved', 'info')
  expect(reportMessage).toHaveBeenCalledWith('telemetry:saved:props {"count":1}', 'info')
  vi.mocked(reportMessage).mockImplementation(() => { throw new Error('unavailable') })
  expect(() => track('sink-down')).not.toThrow()
})
