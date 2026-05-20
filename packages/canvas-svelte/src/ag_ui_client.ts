// AG-UI WebSocket client (Vue + Svelte share the same shape).
//
// Mirrors the *decoding contract* of the Dart `AgUiClient` in
// `forge-canvas-dart`: a caller-supplied parser turns each inbound
// JSON frame into a typed event, fired through `onEvent`. The
// transport differs by design — Dart is SSE/POST (the deepagent
// `runAgent` contract); Vue + Svelte are WebSocket (the
// `agent_streaming` `/ws/agent` endpoint). The decode-and-callback
// shape is the unified surface; the wire underneath follows each
// frontend's existing template.
//
// Initiative #4: events flow with `kind` as the canonical discriminator
// in a wrapped envelope (`{kind, payload}`). The backend Pydantic
// union and the Dart `AgUiEvent.parse` factory both produce/consume
// that shape. TS consumers narrow on `event.kind` and read fields
// off `event.payload`.
//
// Usage with the generated discriminated union:
//
//     import { AgUiClient } from '@forge/canvas-svelte'
//     import type { AgUiEvent } from './generated/events'
//
//     function parse(frame: Record<string, unknown>): AgUiEvent | null {
//       const kind = frame.kind
//       const payload = frame.payload
//       if (typeof kind !== 'string') return null
//       if (payload === null || typeof payload !== 'object') return null
//       return frame as AgUiEvent  // wire is already {kind, payload}
//     }
//
//     const client = new AgUiClient<AgUiEvent>({
//       url: `ws://${host}/api/v1/ws/agent`,
//       parser: parse,
//       onEvent: (ev) => {
//         switch (ev.kind) {
//           case 'agent-state':   /* ev.payload: AgentState */ break
//           // ...assertUnreachable(ev) at the default to enforce coverage.
//         }
//       },
//     })
//     client.connect()
//     client.send({ content: 'hi' })

export interface AgUiClientOptions<E> {
  /** WebSocket URL to connect to (e.g. `ws://host/api/v1/ws/agent`). */
  url: string
  /** Decode a JSON-parsed frame into the typed event union. Return `null` to drop. */
  parser: (frame: Record<string, unknown>) => E | null
  /** Called for each decoded event. */
  onEvent: (event: E) => void
  /** Optional hook for malformed/unparseable frames — passes the raw text. */
  onParseError?: (raw: string) => void
  /** Optional hook for socket-level errors. */
  onSocketError?: (event: Event) => void
  /** Optional hook fired when the socket closes (clean or otherwise). */
  onClose?: (event: CloseEvent) => void
  /** Override the `WebSocket` constructor — useful for tests. */
  webSocketFactory?: (url: string) => WebSocket
}

export class AgUiClient<E> {
  private socket: WebSocket | null = null
  private readonly options: AgUiClientOptions<E>

  constructor(options: AgUiClientOptions<E>) {
    this.options = options
  }

  /** Open the WebSocket. Idempotent — calling twice is a no-op. */
  connect(): void {
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) return
    const factory = this.options.webSocketFactory ?? ((url) => new WebSocket(url))
    const ws = factory(this.options.url)
    ws.onmessage = (event: MessageEvent) => this.handleFrame(String(event.data))
    if (this.options.onSocketError) ws.onerror = this.options.onSocketError
    if (this.options.onClose) ws.onclose = this.options.onClose
    this.socket = ws
  }

  /** Send a JSON-encoded payload over the open WebSocket. */
  send(payload: Record<string, unknown>): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error('AgUiClient: WebSocket is not open')
    }
    this.socket.send(JSON.stringify(payload))
  }

  /** Close the WebSocket. Safe to call multiple times. */
  close(code?: number, reason?: string): void {
    if (!this.socket) return
    this.socket.close(code, reason)
    this.socket = null
  }

  private handleFrame(raw: string): void {
    let decoded: unknown
    try {
      decoded = JSON.parse(raw)
    } catch {
      this.options.onParseError?.(raw)
      return
    }
    if (decoded === null || typeof decoded !== 'object' || Array.isArray(decoded)) {
      this.options.onParseError?.(raw)
      return
    }
    const event = this.options.parser(decoded as Record<string, unknown>)
    if (event !== null) this.options.onEvent(event)
  }
}
