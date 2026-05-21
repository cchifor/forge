// MCP client-side hook — caches tool registry + enforces approval mode.
//
// Wire-protocol fix (Pillar B Phase 1 of the architectural improvement plan):
// before this rewrite, `invoke()` POSTed to `/mcp/invoke` with no
// `approval_token`, but the Python backend requires one whenever
// `approval_mode != "auto"` and rejects with HTTP 401 otherwise. Every
// non-auto invocation 401'd; the bug was masked by the MCP UI panels
// being stubs that nobody routed real traffic through. This
// implementation:
//
//   1. After the user approves, POST /mcp/approval/mint to get a
//      signed token (HMAC-SHA256, TTL 3600s — see audit.py).
//   2. POST /mcp/invoke with { ...payload, approval_token } so the
//      backend's `verify_approval_token` passes.
//   3. Cache the token per (server, tool, input-hash) for the session
//      so repeated `prompt-once` invocations reuse it until either
//      TTL expiry or the user explicitly resets.
//
// TODO(Pillar B Phase 2): once `forge_canvas_core` ships on pub.dev
// the algorithm below collapses into `McpApprovalClient` from that
// package. Until then, the inline version below MUST stay
// algorithmically equivalent to the TS `McpApprovalClient` in
// `packages/canvas-core/src/mcp_approval_client.ts` so the cross-stack
// contract is honest.
//
// Pairs with lib/src/features/mcp/tool_registry.dart + approval_dialog.dart.
// Callers construct one McpClient per app, hand the BuildContext of the
// requesting surface to `invoke` so the approval dialog can render above it.

import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;

import 'approval_dialog.dart';
import 'tool_registry.dart';

class _CachedToken {
  final String token;
  final DateTime expiresAt;

  _CachedToken({required this.token, required this.expiresAt});
}

class McpClient {
  /// Default TTL matches the backend's MCP_APPROVAL_TOKEN_TTL_SECONDS
  /// (`audit.py` line 130) minus a 30s safety margin to avoid edge-of-TTL
  /// races between the client's clock and the backend's.
  static const Duration _tokenTtl = Duration(seconds: 3600 - 30);

  final Uri baseUrl;
  final http.Client _http;
  final Map<String, bool> _sessionApprovals = {};
  final Map<String, _CachedToken> _tokenCache = {};
  List<McpTool>? _toolsCache;

  McpClient({required this.baseUrl, http.Client? client})
      : _http = client ?? http.Client();

  Future<List<McpTool>> refresh() async {
    final response = await _http.get(baseUrl.resolve('/mcp/tools'));
    if (response.statusCode != 200) {
      throw Exception('GET /mcp/tools ${response.statusCode}');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! List) throw Exception('expected list');
    _toolsCache = decoded
        .whereType<Map<String, dynamic>>()
        .map(McpTool.fromJson)
        .toList();
    return _toolsCache!;
  }

  Future<Object?> invoke({
    required BuildContext context,
    required String server,
    required String tool,
    required Map<String, dynamic> input,
  }) async {
    final tools = _toolsCache ?? await refresh();
    final match = tools.firstWhere(
      (t) => t.server == server && t.name == tool,
      orElse: () => throw Exception('MCP tool not found: $server:$tool'),
    );

    final key = '$server:$tool';
    final already = _sessionApprovals[key];
    if (already == false) throw Exception('user denied tool: $key');

    if (match.approvalMode != 'auto' && already != true) {
      final result = await showDialog<ApprovalResult>(
        context: context,
        barrierDismissible: false,
        builder: (_) => ApprovalDialog(
          toolName: tool,
          server: server,
          inputPreview: const JsonEncoder.withIndent('  ').convert(input),
          defaultMode: match.approvalMode,
        ),
      );
      final approved = result?.approved ?? false;
      if (match.approvalMode == 'prompt-once' && result != null) {
        _sessionApprovals[key] = approved;
      }
      if (!approved) throw Exception('user denied tool: $key');
    }

    // Backend gates non-auto modes on `approval_token`; mint then send.
    final body = <String, dynamic>{
      'server': server,
      'tool': tool,
      'input': input,
    };
    if (match.approvalMode != 'auto') {
      body['approval_token'] = await _mintApprovalToken(server: server, tool: tool, input: input);
    }

    final response = await _http.post(
      baseUrl.resolve('/mcp/invoke'),
      headers: {'content-type': 'application/json'},
      body: jsonEncode(body),
    );
    if (response.statusCode == 401) {
      // Token was rejected — most likely it expired between mint and
      // invoke, or the backend secret rotated. Evict the cache so the
      // next call re-mints and surface a clear error so the UI can
      // re-prompt rather than silently retrying.
      _tokenCache.remove(_tokenCacheKey(server: server, tool: tool, input: input));
      throw Exception(
        'MCP approval token rejected for $server:$tool. '
        'Re-approve to mint a fresh token.',
      );
    }
    if (response.statusCode != 200) {
      throw Exception('POST /mcp/invoke ${response.statusCode}');
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    if (payload['ok'] != true) {
      throw Exception(payload['error']?.toString() ?? 'MCP invoke failed');
    }
    return payload['output'];
  }

  /// Mint or reuse an approval token for `(server, tool, input)`.
  ///
  /// Cache is keyed on the JSON-encoded input because the backend's
  /// HMAC signature is bound to a hash of the input — a changed input
  /// invalidates the token, so caching on input matches that contract.
  Future<String> _mintApprovalToken({
    required String server,
    required String tool,
    required Map<String, dynamic> input,
  }) async {
    final key = _tokenCacheKey(server: server, tool: tool, input: input);
    final cached = _tokenCache[key];
    if (cached != null && cached.expiresAt.isAfter(DateTime.now())) {
      return cached.token;
    }
    final response = await _http.post(
      baseUrl.resolve('/mcp/approval/mint'),
      headers: {'content-type': 'application/json'},
      body: jsonEncode({'server': server, 'tool': tool, 'input': input}),
    );
    if (response.statusCode != 200) {
      throw Exception(
        'Failed to mint MCP approval token for $server:$tool '
        '(status ${response.statusCode})',
      );
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    final token = payload['token'];
    if (token is! String || token.isEmpty) {
      throw Exception('MCP approval mint returned no token for $server:$tool');
    }
    _tokenCache[key] = _CachedToken(
      token: token,
      expiresAt: DateTime.now().add(_tokenTtl),
    );
    return token;
  }

  /// Force-evict any cached token for this tuple. Useful when the caller
  /// knows the input is about to change so the next invoke re-mints.
  void evictToken({
    required String server,
    required String tool,
    required Map<String, dynamic> input,
  }) {
    _tokenCache.remove(_tokenCacheKey(server: server, tool: tool, input: input));
  }

  /// Reset all cached tokens (e.g. on logout).
  void clearTokenCache() => _tokenCache.clear();

  String _tokenCacheKey({
    required String server,
    required String tool,
    required Map<String, dynamic> input,
  }) =>
      '$server::$tool::${jsonEncode(input)}';
}
