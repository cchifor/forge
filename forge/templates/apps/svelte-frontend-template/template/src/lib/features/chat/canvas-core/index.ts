/**
 * `@forge/canvas-core` — framework-agnostic AG-UI runtime.
 *
 * Consumed by `@forge/canvas-vue` and `@forge/canvas-svelte` (TS) and
 * `forge_canvas` (Dart, mirror in `packages/forge-canvas-dart/`).
 *
 * Pillar B Phase 1 of the architectural improvement plan ships:
 *
 *   - Pure AG-UI reducer + snapshot types (this package).
 *   - SSE-based `AgUiClient<E>` with reconnect + Last-Event-ID resume.
 *   - `McpApprovalClient` — the wire-protocol bug fix for non-`auto`
 *     MCP tool invocations.
 *   - Typed `McpBridge` wrapping the upstream `@modelcontextprotocol/
 *     ext-apps/app-bridge`.
 *
 * The per-stack `useAgentClient` rewrite (Pillar B Steps 3–4) lands
 * in a follow-up PR; this package is the upstream dep that makes
 * that rewrite mechanical.
 */

// AG-UI event union + parser.
export {
  parseEvent,
  type ActivitySnapshotEvent,
  type AgUiEvent,
  type CustomEvent,
  type MessagesSnapshotEvent,
  type RunErrorEvent,
  type RunFinishedEvent,
  type RunStartedEvent,
  type StateDeltaEvent,
  type StateSnapshotEvent,
  type TextMessageContentEvent,
  type TextMessageEndEvent,
  type TextMessageStartEvent,
  type ToolCallArgsEvent,
  type ToolCallEndEvent,
  type ToolCallStartEvent,
  type UnknownEvent,
} from './events.js'

// Snapshot types + defaults.
export {
  agentStateFromRaw,
  EMPTY_AGENT_STATE,
  EMPTY_CHAT_SNAPSHOT,
  type AgentState,
  type ChatMessage,
  type ChatRole,
  type ChatStateSnapshot,
  type ToolCallInfo,
  type ToolCallStatus,
  type UserPromptOption,
  type UserPromptPayload,
  type WorkspaceActivity,
} from './snapshot.js'

// Pure reducer.
export { clearPendingPromptIfMatches, reduce, resetSnapshot } from './reducer.js'

// SSE client.
export {
  AgUiClient,
  splitOnFrameBoundary,
  type AgUiClientOptions,
  type AgUiRunPayload,
} from './ag_ui_client.js'

// MCP — approval-aware tool invocation (wire-bug fix) + iframe bridge.
export {
  McpApprovalClient,
  McpApprovalRejected,
  type ApprovalMode,
  type McpApprovalClientOptions,
  type McpInvokeRequest,
  type McpInvokeResult,
} from './mcp_approval_client.js'

export {
  createMcpBridge,
  MCP_BRIDGE_AVAILABLE,
  mountMcpExtBridge,
  type AppBridgeCapabilities,
  type AppBridgeConstructor,
  type AppBridgeContext,
  type AppBridgeIdentity,
  type BridgeMessage,
  type IframeSizeChange,
  type McpBridge,
  type McpBridgeHandlers,
  type MountMcpExtBridgeCallbacks,
  type MountMcpExtBridgeHandle,
  type MountMcpExtBridgeOptions,
  type OpenLinkRequest,
  type PostMessageTransportConstructor,
  type ToolCallRequest,
  type UpstreamAppBridge,
} from './mcp_bridge.js'
