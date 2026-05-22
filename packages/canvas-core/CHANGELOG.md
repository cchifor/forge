# Changelog

## 1.0.0-alpha.2 — unreleased

- Add `mountMcpExtBridge(options)` helper — wraps the construction +
  handler wiring + `connect()` + `sendSandboxResourceReady` flow that
  the Vue + Svelte `McpExtEngine` templates each implement inline.
  Takes `AppBridge` and `PostMessageTransport` constructors as
  injected arguments so canvas-core stays free of the
  `@modelcontextprotocol/ext-apps` dep. Returns `{ cleanup,
  sendToolInput, sendToolResult }` handles and guards against the
  unmount-during-connect race that the templates handle explicitly.
- Extend `UpstreamAppBridge` with `sendSandboxResourceReady({html,
  csp, permissions})`.
- New exported types: `AppBridgeConstructor`,
  `PostMessageTransportConstructor`, `MountMcpExtBridgeOptions`,
  `MountMcpExtBridgeCallbacks`, `MountMcpExtBridgeHandle`.

## 1.0.0-alpha.1 — unreleased

- Initial release. Framework-agnostic AG-UI reducer + snapshot types,
  SSE-based `AgUiClient<E>` with reconnect + Last-Event-ID resume,
  `McpApprovalClient` (wire-protocol bug fix for non-`auto` MCP tool
  invocations), and typed `McpBridge` wrapping the upstream
  `@modelcontextprotocol/ext-apps/app-bridge`.
