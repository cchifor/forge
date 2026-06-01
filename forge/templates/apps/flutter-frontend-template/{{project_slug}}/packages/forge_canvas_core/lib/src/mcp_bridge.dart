/// Typed contract for the MCP iframe bridge (Dart stub).
///
/// Mirrors `@forge/canvas-core/src/mcp_bridge.ts` so the cross-stack
/// contract stays honest by construction. **This Dart module is a
/// no-DOM stub by design** — the TS module wraps the upstream
/// `@modelcontextprotocol/ext-apps/app-bridge` JS package that talks
/// `postMessage` to a sandboxed iframe. Flutter has no equivalent
/// runtime on the main thread; a real Flutter MCP-ext implementation
/// belongs in a separate webview package and is out of scope here.
///
/// What this module ships:
///
///   * The interface types ([McpBridge], [McpBridgeHandlers],
///     [BridgeMessage], [ToolCallRequest], [OpenLinkRequest],
///     [IframeSizeChange]) so the cross-stack TS↔Dart contract is
///     visible in pubspec and `dart analyze` — drift between the two
///     stacks surfaces at compile time rather than at runtime.
///   * [mcpBridgeAvailable] — `false` constant. Flutter `McpExtEngine`
///     widgets read this and short-circuit to a no-op UI rather than
///     throwing on a missing DOM global. Mirrors the TS
///     `MCP_BRIDGE_AVAILABLE` flag which evaluates to `true` in the
///     browser/Electron and `false` in CLI/Node-without-DOM.
///
/// TODO(phase-3): a real Flutter implementation backed by
/// `webview_flutter` would live in a separate `forge_canvas_webview`
/// package. The decision to keep this stub (rather than ship a fake
/// implementation that lies about its capabilities) is deliberate and
/// tracked in Pillar F of the architectural plan.

/// Identity advertised to the bridge upstream — matches the TS
/// `AppBridgeIdentity`.
class AppBridgeIdentity {
  const AppBridgeIdentity({required this.name, required this.version});

  /// Human-readable name of the embedding app (shown in dev tools).
  final String name;

  /// Semver — bump on breaking host-context changes.
  final String version;
}

/// Bridge capabilities — matches the TS `AppBridgeCapabilities`.
class AppBridgeCapabilities {
  const AppBridgeCapabilities({this.openLinks, this.logging});

  /// Whitelist for `bridge.onOpenLink` — empty map means deny-all.
  final Map<String, dynamic>? openLinks;

  /// Bridge-side logging config (delegated to the upstream package).
  final Map<String, dynamic>? logging;
}

/// Host context handed to the bridged iframe — matches the TS
/// `AppBridgeContext`.
class AppBridgeContext {
  const AppBridgeContext({required this.hostContext});

  final Map<String, dynamic> hostContext;
}

/// A tool-call request the iframe forwards back to the host.
class ToolCallRequest {
  const ToolCallRequest({required this.name, required this.arguments});

  final String name;
  final Map<String, dynamic> arguments;
}

/// An open-external-link request from the iframe.
class OpenLinkRequest {
  const OpenLinkRequest({required this.url});

  final String url;
}

/// Iframe resize notification.
class IframeSizeChange {
  const IframeSizeChange({required this.height, this.width});

  final double height;
  final double? width;
}

/// Inbound message from the iframe.
class BridgeMessage {
  const BridgeMessage({required this.content, this.meta});

  final String content;

  /// Optional structured metadata (e.g. message origin id, role).
  final Map<String, dynamic>? meta;
}

/// Inbound iframe handler set installed onto a [McpBridge]. Mirrors
/// the TS `McpBridgeHandlers` interface.
class McpBridgeHandlers {
  const McpBridgeHandlers({
    this.onInitialized,
    this.onMessage,
    this.onOpenLink,
    this.onSizeChange,
    this.onToolCall,
  });

  final void Function()? onInitialized;
  final Future<void> Function(BridgeMessage msg)? onMessage;
  final Future<void> Function(OpenLinkRequest req)? onOpenLink;
  final void Function(IframeSizeChange size)? onSizeChange;

  /// Returns the tool's result payload (whatever shape your backend
  /// expects). The bridge round-trips it back to the iframe.
  final Future<dynamic> Function(ToolCallRequest req)? onToolCall;
}

/// The bridge surface a host adapter consumes. Implementors must be
/// idempotent on [close]. Mirrors the TS `McpBridge` interface.
abstract class McpBridge {
  /// Forward an inbound iframe handler set to the upstream bridge.
  void on(McpBridgeHandlers handlers);

  /// Resolve a pending tool call with its result payload.
  void sendToolResult(dynamic result);

  /// Disconnect and free the bridge. Idempotent.
  Future<void> close();
}

/// `true` when the runtime can host an iframe-based MCP-ext bridge
/// (browser / Electron / webview).
///
/// Dart consumers (Flutter on iOS/Android/desktop, plain Dart on
/// servers and CLIs) get `false` so their `McpExtEngine` widget
/// short-circuits to a no-op UI rather than throwing on the missing
/// browser globals. A Flutter webview-backed bridge would live in a
/// sibling package and flip this to `true` for that consumer-side
/// build.
const bool mcpBridgeAvailable = false;
