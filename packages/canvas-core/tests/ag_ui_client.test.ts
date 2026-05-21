/**
 * SSE client — frame parsing + reconnect.
 *
 * `splitOnFrameBoundary` is exported for direct testing; the full
 * `AgUiClient` is exercised against a mocked `fetch` returning a
 * `ReadableStream` of SSE bytes.
 */

import { describe, expect, it } from 'vitest'
import {
  AgUiClient,
  splitOnFrameBoundary,
  parseEvent,
  type AgUiEvent,
} from '../src/index.js'

describe('splitOnFrameBoundary', () => {
  it('returns null without a complete frame', () => {
    expect(splitOnFrameBoundary('data: hi')).toBeNull()
  })

  it('splits on LF\\nLF', () => {
    const [frame, rest] = splitOnFrameBoundary('data: hi\n\ndata: bye\n\n')!
    expect(frame).toBe('data: hi')
    expect(rest).toBe('data: bye\n\n')
  })

  it('splits on CRLF\\r\\nCRLF', () => {
    const [frame, rest] = splitOnFrameBoundary('data: hi\r\n\r\ntail')!
    expect(frame).toBe('data: hi')
    expect(rest).toBe('tail')
  })
})

function makeSseResponse(frames: string[]): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  })
}

describe('AgUiClient — happy path', () => {
  it('consumes a multi-frame SSE stream', async () => {
    const events: AgUiEvent[] = []
    const fakeFetch = (async () =>
      makeSseResponse([
        'data: {"type":"RUN_STARTED"}\n\n',
        'data: {"type":"TEXT_MESSAGE_START","messageId":"m1","role":"assistant"}\n\n',
        'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"m1","delta":"hi"}\n\n',
        'data: {"type":"RUN_FINISHED"}\n\n',
      ])) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: (e) => events.push(e),
      fetch: fakeFetch,
    })
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(events.map((e) => e.type)).toEqual([
      'RUN_STARTED',
      'TEXT_MESSAGE_START',
      'TEXT_MESSAGE_CONTENT',
      'RUN_FINISHED',
    ])
  })

  it('handles multi-line data fields', async () => {
    const events: AgUiEvent[] = []
    const fakeFetch = (async () =>
      makeSseResponse([
        'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"m1",\ndata: "delta":"hi"}\n\n',
      ])) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: (e) => events.push(e),
      fetch: fakeFetch,
    })
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(events).toHaveLength(1)
    expect(events[0]?.type).toBe('TEXT_MESSAGE_CONTENT')
  })

  it('persists Last-Event-ID across frames', async () => {
    const events: AgUiEvent[] = []
    const captured: Record<string, string> = {}
    const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const headers = init?.headers as Record<string, string> | undefined
      if (headers) {
        for (const [k, v] of Object.entries(headers)) {
          captured[k.toLowerCase()] = v
        }
      }
      return makeSseResponse([
        'id: 42\ndata: {"type":"RUN_STARTED"}\n\n',
      ])
    }) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: (e) => events.push(e),
      fetch: fakeFetch,
    })
    // First connect doesn't send last-event-id.
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(captured['last-event-id']).toBeUndefined()

    // Second connect should include it.
    await client.runAgent({ threadId: 't1', runId: 'r2' })
    expect(captured['last-event-id']).toBe('42')
  })

  it('calls onParseError on malformed JSON', async () => {
    const errors: string[] = []
    const fakeFetch = (async () =>
      makeSseResponse(['data: not-json\n\n'])) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: () => {},
      onParseError: (raw) => errors.push(raw),
      fetch: fakeFetch,
    })
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(errors).toEqual(['not-json'])
  })

  it('ignores SSE comment lines', async () => {
    const events: AgUiEvent[] = []
    const fakeFetch = (async () =>
      makeSseResponse([
        ': heartbeat\ndata: {"type":"RUN_STARTED"}\n\n',
      ])) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: (e) => events.push(e),
      fetch: fakeFetch,
    })
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(events).toHaveLength(1)
  })
})

describe('AgUiClient — reconnect', () => {
  it('without reconnect, surfaces the first error and exits', async () => {
    const errors: unknown[] = []
    const fakeFetch = (async () => {
      throw new Error('network down')
    }) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: () => {},
      onConnectionError: (e) => errors.push(e),
      fetch: fakeFetch,
    })
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(errors).toHaveLength(1)
  })

  it('with reconnect, retries until success', async () => {
    let attempt = 0
    const events: AgUiEvent[] = []
    const errors: unknown[] = []
    const fakeFetch = (async () => {
      attempt++
      if (attempt === 1) throw new Error('transient')
      return makeSseResponse(['data: {"type":"RUN_STARTED"}\n\n'])
    }) as unknown as typeof globalThis.fetch
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: (e) => events.push(e),
      onConnectionError: (e) => errors.push(e),
      fetch: fakeFetch,
      reconnect: true,
      initialBackoffMs: 1, // keep the test fast
      maxBackoffMs: 5,
    })
    await client.runAgent({ threadId: 't1', runId: 'r1' })
    expect(events).toHaveLength(1)
    expect(errors).toHaveLength(1) // the first attempt is surfaced
  })

  it('aborts cleanly via AbortSignal', async () => {
    const fakeFetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      const signal = init?.signal ?? undefined
      return new Response(
        new ReadableStream({
          start(controller) {
            // Honour abort by erroring the stream — mirrors browser
            // `fetch` semantics where aborting the request errors the
            // underlying ReadableStream reader.
            if (signal) {
              signal.addEventListener(
                'abort',
                () => controller.error(new DOMException('aborted', 'AbortError')),
                { once: true },
              )
            }
          },
        }),
      )
    }) as unknown as typeof globalThis.fetch
    const ac = new AbortController()
    const client = new AgUiClient<AgUiEvent>({
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: () => {},
      fetch: fakeFetch,
    })
    // Abort almost immediately.
    setTimeout(() => ac.abort(), 20)
    await client.runAgent({ threadId: 't1', runId: 'r1' }, ac.signal)
    // Just reaching here means the runAgent returned; the test would
    // hang otherwise.
    expect(ac.signal.aborted).toBe(true)
  })
})
