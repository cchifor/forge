/**
 * Circuit breaker factory using opossum.
 *
 * Usage:
 *
 *     import { breaker } from './lib/circuit-breaker'
 *
 *     const call = breaker('openai', (args) => openai.chat(args), {
 *       timeout: 30_000,
 *       errorThresholdPercentage: 50,
 *     })
 *     const result = await call(payload)
 *
 * Env overrides (apply to every breaker):
 *   CIRCUIT_BREAKER_TIMEOUT_MS, CIRCUIT_BREAKER_ERROR_THRESHOLD_PCT,
 *   CIRCUIT_BREAKER_RESET_TIMEOUT_MS.
 */
import CircuitBreaker, { type Options } from 'opossum'

const DEFAULT_TIMEOUT_MS = Number(process.env.CIRCUIT_BREAKER_TIMEOUT_MS ?? "10000")
const DEFAULT_ERROR_THRESHOLD = Number(process.env.CIRCUIT_BREAKER_ERROR_THRESHOLD_PCT ?? "50")
const DEFAULT_RESET_MS = Number(process.env.CIRCUIT_BREAKER_RESET_TIMEOUT_MS ?? "30000")

export function breaker<Input, Output>(
  name: string,
  action: (input: Input) => Promise<Output>,
  overrides: Partial<Options> = {},
): (input: Input) => Promise<Output> {
  const cb = new CircuitBreaker(action, {
    name,
    timeout: DEFAULT_TIMEOUT_MS,
    errorThresholdPercentage: DEFAULT_ERROR_THRESHOLD,
    resetTimeout: DEFAULT_RESET_MS,
    ...overrides,
  })
  return (input: Input) => cb.fire(input) as Promise<Output>
}
