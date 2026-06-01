/**
 * SSE-based AG-UI client with reconnect + Last-Event-ID resume.
 *
 * Mirrors the Dart `AgUiClient<E>` reference at
 * `packages/forge-canvas-dart/lib/src/ag_ui_client.dart` because the
 * Dart side already shipped the only complete client (the existing
 * `packages/canvas-{vue,svelte}/src/ag_ui_client.ts` are WebSocket
 * shims with no reconnect / no resume — per the architectural plan).
 *
 * Wire format: AG-UI servers respond with `text/event-stream`. Each
 * frame is a `data: ...` line (possibly multi-line, joined with `\n`)
 * separated by blank lines. `id: ...` lines persist as the most-recent
 * event id, sent back as `Last-Event-ID` on reconnect for server-side
 * resume.
 *
 * Reconnect: opt-in via `reconnect: true`. Exponential backoff between
 * `initialBackoffMs` and `maxBackoffMs`, with jitter. Resets to the
 * initial delay on the first successful event. Hard-stops on
 * `AbortController.abort()` from the caller.
 */

const DEFAULT_INITIAL_BACKOFF_MS = 500
const DEFAULT_MAX_BACKOFF_MS = 30_000
const DEFAULT_BACKOFF_JITTER = 0.25

export interface AgUiClientOptions<E> {
  /** URL the agent serves SSE from (e.g. `/agent/`). Required. */
  url: string
  /**
   * Parse a raw decoded frame (already JSON.parsed) into a typed event.
   * Return `null` to drop the frame silently (useful for
   * forward-compat shapes the client doesn't understand yet).
   */
  parser: (frame: Record<string, unknown>) => E | null
  /** Called for each successfully parsed event. */
  onEvent: (event: E) => void
  /**
   * Called when the server emits malformed JSON or a frame the parser
   * rejected (returned `null`). Defaults to `console.warn`.
   */
  onParseError?: (raw: string, cause?: unknown) => void
  /**
   * Called when the underlying fetch / SSE stream errors. Reconnect is
   * still attempted if `reconnect: true`. Defaults to `console.warn`.
   */
  onConnectionError?: (error: unknown) => void
  /**
   * Whether to reconnect on connection failure. Defaults to `false` —
   * the caller should opt in explicitly because long-running agent
   * runs may want to surface failures rather than silently retry.
   */
  reconnect?: boolean
  initialBackoffMs?: number
  maxBackoffMs?: number
  /** Extra HTTP headers (e.g. `Authorization`). */
  headers?: Record<string, string>
  /** Optional `fetch` override for testing. Defaults to `globalThis.fetch`. */
  fetch?: typeof globalThis.fetch
}

export interface AgUiRunPayload {
  threadId: string
  runId: string
  /** Free-form; passed to the agent verbatim. */
  messages?: unknown[]
  state?: Record<string, unknown>
  tools?: unknown[]
  context?: unknown[]
  forwardedProps?: Record<string, unknown>
}

export class AgUiClient<E> {
  private readonly options: Required<
    Omit<
      AgUiClientOptions<E>,
      'headers' | 'fetch' | 'onParseError' | 'onConnectionError'
    >
  > & {
    headers: Record<string, string>
    fetch: typeof globalThis.fetch
    onParseError: (raw: string, cause?: unknown) => void
    onConnectionError: (error: unknown) => void
  }

  private lastEventId: string | null = null
  private currentBackoff: number

  constructor(options: AgUiClientOptions<E>) {
    this.options = {
      url: options.url,
      parser: options.parser,
      onEvent: options.onEvent,
      onParseError:
        options.onParseError ??
        ((raw: string, cause?: unknown) =>
          console.warn('[canvas-core] failed to parse AG-UI frame', { raw, cause })),
      onConnectionError:
        options.onConnectionError ??
        ((error: unknown) =>
          console.warn('[canvas-core] AG-UI connection error', error)),
      reconnect: options.reconnect ?? false,
      initialBackoffMs: options.initialBackoffMs ?? DEFAULT_INITIAL_BACKOFF_MS,
      maxBackoffMs: options.maxBackoffMs ?? DEFAULT_MAX_BACKOFF_MS,
      headers: options.headers ?? {},
      fetch: options.fetch ?? globalThis.fetch.bind(globalThis),
    }
    this.currentBackoff = this.options.initialBackoffMs
  }

  /**
   * Run an agent invocation; consume the SSE stream until the server
   * closes it (or `signal.abort()` fires). When `reconnect=true`,
   * transient failures are retried with backoff; otherwise the first
   * connection error surfaces via `onConnectionError` and the call
   * returns.
   */
  async runAgent(payload: AgUiRunPayload, signal?: AbortSignal): Promise<void> {
    while (!signal?.aborted) {
      try {
        await this.connectOnce(payload, signal)
        // Server closed cleanly — exit the reconnect loop too.
        return
      } catch (error) {
        if (signal?.aborted) return
        this.options.onConnectionError(error)
        if (!this.options.reconnect) return
        await this.sleepWithJitter(this.currentBackoff, signal)
        this.currentBackoff = Math.min(this.currentBackoff * 2, this.options.maxBackoffMs)
      }
    }
  }

  /** Reset reconnect backoff to the initial delay. */
  resetBackoff(): void {
    this.currentBackoff = this.options.initialBackoffMs
  }

  private async connectOnce(
    payload: AgUiRunPayload,
    signal?: AbortSignal,
  ): Promise<void> {
    const headers: Record<string, string> = {
      accept: 'text/event-stream',
      'content-type': 'application/json',
      ...this.options.headers,
    }
    if (this.lastEventId !== null) {
      headers['last-event-id'] = this.lastEventId
    }
    const res = await this.options.fetch(this.options.url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
    })
    if (!res.ok) {
      throw new Error(`AG-UI server returned ${res.status} ${res.statusText}`)
    }
    if (!res.body) {
      throw new Error('AG-UI server response has no body')
    }
    await this.consumeStream(res.body, signal)
  }

  private async consumeStream(body: ReadableStream<Uint8Array>, signal?: AbortSignal) {
    const decoder = new TextDecoder()
    const reader = body.getReader()
    let buffer = ''
    let sawFirstEvent = false
    try {
      while (!signal?.aborted) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let split = splitOnFrameBoundary(buffer)
        while (split !== null) {
          const [frame, rest] = split
          buffer = rest
          if (frame.trim()) {
            this.handleFrame(frame)
            if (!sawFirstEvent) {
              sawFirstEvent = true
              this.resetBackoff()
            }
          }
          split = splitOnFrameBoundary(buffer)
        }
      }
      // Flush any trailing decode + final frame at EOF.
      buffer += decoder.decode()
      if (buffer.trim()) this.handleFrame(buffer)
    } finally {
      try {
        reader.releaseLock()
      } catch {
        // ReadableStreamReader.releaseLock can throw if the stream was
        // already errored — safe to swallow at shutdown time.
      }
    }
  }

  private handleFrame(rawFrame: string): void {
    // Parse SSE frame: lines starting `data:`, `id:`, `event:`,
    // `retry:`. We only care about `data` + `id`; comments (`: ...`)
    // are ignored.
    const dataLines: string[] = []
    for (const line of rawFrame.split('\n')) {
      if (line.startsWith(':')) continue
      const colonIdx = line.indexOf(':')
      const field = colonIdx === -1 ? line : line.slice(0, colonIdx)
      // SSE allows an optional single space after the colon.
      let value = colonIdx === -1 ? '' : line.slice(colonIdx + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'data') {
        dataLines.push(value)
      } else if (field === 'id') {
        this.lastEventId = value
      }
      // We deliberately don't parse `event:` / `retry:` — AG-UI uses
      // a single `data:` channel with the event type embedded in the
      // JSON payload.
    }
    if (dataLines.length === 0) return
    const payload = dataLines.join('\n')
    let frame: Record<string, unknown>
    try {
      const decoded = JSON.parse(payload)
      if (typeof decoded !== 'object' || decoded === null || Array.isArray(decoded)) {
        this.options.onParseError(payload, new Error('frame must be a JSON object'))
        return
      }
      frame = decoded as Record<string, unknown>
    } catch (err) {
      this.options.onParseError(payload, err)
      return
    }
    const event = this.options.parser(frame)
    if (event === null) {
      this.options.onParseError(payload, new Error('parser rejected frame'))
      return
    }
    this.options.onEvent(event)
  }

  private async sleepWithJitter(baseMs: number, signal?: AbortSignal): Promise<void> {
    const jitter = baseMs * DEFAULT_BACKOFF_JITTER * Math.random()
    const sleep = baseMs + jitter
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        signal?.removeEventListener('abort', onAbort)
        resolve()
      }, sleep)
      const onAbort = () => {
        clearTimeout(timer)
        reject(new DOMException('aborted', 'AbortError'))
      }
      if (signal) {
        if (signal.aborted) {
          clearTimeout(timer)
          reject(new DOMException('aborted', 'AbortError'))
          return
        }
        signal.addEventListener('abort', onAbort, { once: true })
      }
    })
  }
}

/**
 * Split an SSE buffer at the first `\n\n` (or `\r\n\r\n`) boundary.
 * Returns `[frame, rest]` or `null` if no complete frame is yet
 * available. Exported for test fixture clarity; consumers shouldn't
 * need it directly.
 */
export function splitOnFrameBoundary(buffer: string): [string, string] | null {
  // SSE frame boundary is two consecutive blank lines per the spec.
  // Accept LF, CRLF, and mixed forms defensively.
  const idx = findFrameBoundary(buffer)
  if (idx === -1) return null
  // Find the length of the boundary we matched (\n\n, \r\n\r\n, etc.)
  // so the rest doesn't accidentally start with stray CR bytes.
  let endOfBoundary = idx + 2
  if (buffer[idx] === '\r' && buffer[idx + 1] === '\n') {
    endOfBoundary = idx + 4
  }
  return [buffer.slice(0, idx), buffer.slice(endOfBoundary)]
}

function findFrameBoundary(buffer: string): number {
  // Try LF-only first since that's the AG-UI server's emit shape.
  const lf = buffer.indexOf('\n\n')
  const crlf = buffer.indexOf('\r\n\r\n')
  if (lf === -1) return crlf
  if (crlf === -1) return lf
  return Math.min(lf, crlf)
}
