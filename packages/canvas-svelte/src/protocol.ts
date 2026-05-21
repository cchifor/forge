// Canvas-svelte protocol surface — the framework-agnostic re-exports
// (no Svelte components). Split out from `index.ts` so vitest can
// import this without triggering `.svelte` preprocessing, which is
// flaky under Vite 6 + Svelte 5 + Vitest today.
//
// `index.ts` re-exports everything in here PLUS the Svelte components,
// so consumers can keep importing from `@forge/canvas-svelte` and get
// both. Test files that don't need components import from
// `@forge/canvas-svelte/protocol` (this file) to side-step the
// preprocessor.

export { AgUiClient } from './ag_ui_client'
export type { AgUiClientOptions } from './ag_ui_client'

export {
  AgUiClient as SseAgUiClient,
  McpApprovalClient,
  McpApprovalRejected,
  createMcpBridge,
  MCP_BRIDGE_AVAILABLE,
  agentStateFromRaw,
  clearPendingPromptIfMatches,
  EMPTY_AGENT_STATE,
  EMPTY_CHAT_SNAPSHOT,
  parseEvent,
  reduce,
  resetSnapshot,
  splitOnFrameBoundary,
} from '@forge/canvas-core'
export type {
  AgUiClientOptions as SseAgUiClientOptions,
  AgUiEvent,
  AgUiRunPayload,
  AgentState,
  ApprovalMode,
  AppBridgeCapabilities,
  AppBridgeContext,
  AppBridgeIdentity,
  BridgeMessage,
  ChatMessage,
  ChatRole,
  ChatStateSnapshot,
  IframeSizeChange,
  McpApprovalClientOptions,
  McpBridge,
  McpBridgeHandlers,
  McpInvokeRequest,
  McpInvokeResult,
  OpenLinkRequest,
  ToolCallInfo,
  ToolCallRequest,
  ToolCallStatus,
  UpstreamAppBridge,
  UserPromptOption,
  UserPromptPayload,
  WorkspaceActivity,
} from '@forge/canvas-core'
