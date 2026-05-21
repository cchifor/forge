// AG-UI WebSocket client (Vue + Svelte share the same shape).
//
// Two AG-UI clients ship in `@forge/canvas-vue`:
//
//   - `AgUiClient` (this file) — **WebSocket** transport for AG-UI-
//     compliant servers emitting the `{kind, payload}` envelope.
//     Best for full-duplex consumers (bidirectional `send()` +
//     `onEvent`).
//   - `SseAgUiClient` (re-exported from `@forge/canvas-core`) — **SSE**
//     transport with reconnect + Last-Event-ID resume. Best for
//     unidirectional agent-run streams (the protocol the Dart
//     `AgUiClient<E>` reference and the agent_streaming HTTP endpoint
//     speak).
//
// Pick by transport, not by package. The protocols are different and
// pointing one at the other's endpoint will silently drop frames.
//
// Wire format — `{kind, payload}` wrapped envelope. The generated
// `AgUiEvent` discriminated union, the Dart `AgUiEvent.parse`
// factory, and the Pydantic AG-UI union in
// `forge/codegen/event_union.py` all produce / consume this shape.
// TS consumers narrow on `event.kind` and read variant fields off
// `event.payload`.
//
// ## Scope: this client targets AG-UI-compliant servers
//
// The seven AG-UI event variants (`ag-ui-payload`, `agent-state`,
// `hitl-response`, `mcp-ext-payload`, `tool-call-info`,
// `user-prompt-payload`, `workspace-activity`) are the AG-UI
// reference protocol — a typed contract for agentic UI streaming.
// Servers that emit these wrapped frames work with this client out
// of the box.
//
// The forge-generated `agent_streaming` `/ws/agent` endpoint does
// NOT emit this wire format. It ships its own simpler streaming
// protocol (`text_delta`, `tool_call_started`,
// `assistant_message_complete`, etc., flat frames with `kind`
// alongside the legacy `type` discriminator) consumed by the
// generated chat templates' own client code. Pointing this
// `AgUiClient` at `/ws/agent` will drop every frame because the
// `kind` vocabularies don't overlap — that's by design, not a bug
// to file against this package.
//
// Usage with an AG-UI-compliant server:
//
//     import { AgUiClient } from '@forge/canvas-vue'
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
//       url: `ws://${host}/ag-ui/events`,  // an AG-UI-compliant route
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
