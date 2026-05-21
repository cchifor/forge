/// MCP approval-aware invocation client (Dart port).
///
/// **This is a wire-protocol bug fix.** Mirrors the TypeScript
/// `@forge/canvas-core/src/mcp_approval_client.ts` line-for-line so the
/// two stacks behave identically against the Python MCP router.
///
/// Background: the Python backend at
/// `forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py`
/// (lines 176-195) requires an HMAC-signed `approval_token` when a
/// tool's `approval_mode != "auto"`. Missing or stale tokens → HTTP 401
/// with `"Approval token missing or invalid. Call /mcp/approval/mint
/// first."` The legacy in-template `mcp_client.dart` calls `/mcp/invoke`
/// directly without ever minting a token; this client fixes that for
/// the cross-stack rewrite.
///
/// This client:
///
///   1. Calls `POST /mcp/approval/mint` with `{server, tool, input}` to
///      get a signed token.
///   2. Calls `POST /mcp/invoke` with `{server, tool, input,
///      approval_token}`.
///   3. Caches the token per `(server, tool, input_hash)` for the
///      session. The backend's signature is bound to a hash of the
///      input, so a changed input would invalidate the token anyway;
///      keying on input keeps the cache honest.
///   4. Refreshes on token expiry (TTL 3600s per `audit.py:130`,
///      trimmed by 30s here to avoid clock-drift races).
///   5. Surfaces 401 errors with a clear remediation message so
///      operators don't have to grep the backend logs — thrown as
///      [McpApprovalRejected] separately from the generic `Exception`
///      so UI layers can show "the backend rejected the approval
///      token — re-approve" rather than a generic network error.
///
/// The `auto` mode short-circuits straight to `/mcp/invoke` without a
/// mint call — the backend doesn't require a token in that mode.

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// Per-tool approval mode. Mirrors the three-state enum in
/// `forge/templates/_shared/mcp/mcp_config_schema.json`.
enum ApprovalMode {
  /// No prompt; invoke directly without minting a token.
  auto,

  /// Prompt once per session, then re-use the cached approval token.
  promptOnce,

  /// Prompt every invocation — the cache is bypassed by caller policy.
  promptEvery;

  /// Wire-format string matching the TS `'auto' | 'prompt-once' |
  /// 'prompt-every'` union and the backend's schema enum.
  String get wireName {
    switch (this) {
      case ApprovalMode.auto:
        return 'auto';
      case ApprovalMode.promptOnce:
        return 'prompt-once';
      case ApprovalMode.promptEvery:
        return 'prompt-every';
    }
  }
}

/// Request envelope passed to [McpApprovalClient.invoke].
class McpInvokeRequest {
  const McpInvokeRequest({
    required this.server,
    required this.tool,
    required this.input,
    required this.approvalMode,
  });

  final String server;
  final String tool;
  final Map<String, dynamic> input;

  /// Per-tool approval mode. When [ApprovalMode.auto], no mint call is
  /// made. Otherwise the client mints a token before invoking. The
  /// Tool Library / Approval Dialog (Pillar F.3 + F.4) is responsible
  /// for actually prompting the user; this client assumes the consent
  /// decision has already been made.
  final ApprovalMode approvalMode;
}

/// Result envelope returned by [McpApprovalClient.invoke]. Mirrors the
/// TS `McpInvokeResult` interface.
class McpInvokeResult {
  const McpInvokeResult({required this.ok, this.output, this.error});

  factory McpInvokeResult.fromJson(Map<String, dynamic> json) {
    return McpInvokeResult(
      ok: json['ok'] == true,
      output: json['output'],
      error: json['error'] as String?,
    );
  }

  final bool ok;
  final dynamic output;
  final String? error;
}

/// One-shot error thrown when invoke returns 401 even after minting.
/// Surfaced separately so UI layers can show "the backend rejected the
/// approval token — re-approve" rather than a generic network error.
class McpApprovalRejected implements Exception {
  McpApprovalRejected({
    required this.server,
    required this.tool,
    required this.status,
    required this.detail,
  });

  final String server;
  final String tool;
  final int status;
  final String detail;

  /// Mirrors the TS `Error.name` field for parity with the JS port.
  String get name => 'McpApprovalRejected';

  String get message =>
      'MCP invocation of $server:$tool rejected with status $status: $detail';

  @override
  String toString() => message;
}

/// Default TTL matches the backend's `MCP_APPROVAL_TOKEN_TTL_SECONDS`.
/// Trimmed by 30s to avoid race conditions on tokens about to expire
/// (the backend's clock and the client's drift).
const Duration _defaultTokenTtl = Duration(seconds: 3600 - 30);

/// Approval-aware MCP tool invocation client.
class McpApprovalClient {
  McpApprovalClient({
    String baseUrl = '',
    http.Client? httpClient,
    Duration? tokenTtl,
    DateTime Function()? now,
  })  : _baseUrl = baseUrl,
        _httpClient = httpClient ?? http.Client(),
        _tokenTtl = tokenTtl ?? _defaultTokenTtl,
        _now = now ?? DateTime.now;

  /// Base URL for the MCP endpoints. Defaults to `""` (same origin) so
  /// the typical Vite proxy + Caddy / Traefik setup works out of the
  /// box. Use an absolute URL for cross-origin host configurations.
  final String _baseUrl;

  /// Optional `http.Client` override for testing or for callers that
  /// need to inject custom headers (e.g. auth Bearer tokens via a
  /// `BaseClient` subclass). Defaults to a fresh `http.Client()`.
  final http.Client _httpClient;

  /// Token TTL. Defaults to 1 hour minus 30s to match the Python
  /// backend's `MCP_APPROVAL_TOKEN_TTL_SECONDS` of 3600.
  final Duration _tokenTtl;

  /// Optional clock for testing — defaults to `DateTime.now`. Reading
  /// from the option lets the cache eviction be deterministic in
  /// tests without freezing global time.
  final DateTime Function() _now;

  final Map<String, _CachedToken> _tokenCache = {};

  /// Invoke an MCP tool, minting an approval token first when required.
  ///
  /// Throws [McpApprovalRejected] on 401 (after mint), wraps other
  /// non-2xx responses in a generic [Exception] with the status + body.
  Future<McpInvokeResult> invoke(McpInvokeRequest req) async {
    String? approvalToken;
    if (req.approvalMode != ApprovalMode.auto) {
      approvalToken = await _ensureToken(req);
    }
    return _invokeWithToken(req, approvalToken);
  }

  /// Force-evict any cached token for this tuple. Useful when the
  /// caller knows the input is about to change (e.g. user edited a
  /// parameter in the approval dialog) so the next invoke re-mints
  /// with the new input rather than failing the server-side hash
  /// check.
  void evict({
    required String server,
    required String tool,
    required Map<String, dynamic> input,
  }) {
    _tokenCache.remove(_cacheKey(server: server, tool: tool, input: input));
  }

  /// Reset all cached tokens. Call on logout, environment switch, or
  /// when the user explicitly chooses "Never remember approvals".
  void clearCache() {
    _tokenCache.clear();
  }

  Future<String> _ensureToken(McpInvokeRequest req) async {
    final key = _cacheKey(server: req.server, tool: req.tool, input: req.input);
    final cached = _tokenCache[key];
    if (cached != null && cached.expiresAt.isAfter(_now())) {
      return cached.token;
    }
    final token = await _mintToken(req);
    _tokenCache[key] = _CachedToken(
      token: token,
      expiresAt: _now().add(_tokenTtl),
    );
    return token;
  }

  Future<String> _mintToken(McpInvokeRequest req) async {
    final res = await _httpClient.post(
      Uri.parse(_url('/mcp/approval/mint')),
      headers: const {'content-type': 'application/json'},
      body: jsonEncode({
        'server': req.server,
        'tool': req.tool,
        'input': req.input,
      }),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(
        'Failed to mint MCP approval token for ${req.server}:${req.tool} '
        '(status ${res.statusCode}): ${_safeBody(res)}',
      );
    }
    final dynamic data = jsonDecode(res.body);
    if (data is! Map<String, dynamic>) {
      throw Exception(
        'MCP approval mint returned a non-object body for '
        '${req.server}:${req.tool}',
      );
    }
    final token = data['token'];
    if (token is! String || token.isEmpty) {
      throw Exception(
        'MCP approval mint returned no token for ${req.server}:${req.tool}',
      );
    }
    return token;
  }

  Future<McpInvokeResult> _invokeWithToken(
    McpInvokeRequest req,
    String? approvalToken,
  ) async {
    final body = <String, dynamic>{
      'server': req.server,
      'tool': req.tool,
      'input': req.input,
    };
    if (approvalToken != null) {
      body['approval_token'] = approvalToken;
    }
    final res = await _httpClient.post(
      Uri.parse(_url('/mcp/invoke')),
      headers: const {'content-type': 'application/json'},
      body: jsonEncode(body),
    );
    if (res.statusCode == 401) {
      // Token was missing/invalid even though we (supposedly) minted
      // one — evict and surface so the UI can prompt for re-approval.
      evict(server: req.server, tool: req.tool, input: req.input);
      throw McpApprovalRejected(
        server: req.server,
        tool: req.tool,
        status: 401,
        detail: _safeBody(res),
      );
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(
        'MCP invoke of ${req.server}:${req.tool} failed '
        '(status ${res.statusCode}): ${_safeBody(res)}',
      );
    }
    final dynamic data = jsonDecode(res.body);
    if (data is! Map<String, dynamic>) {
      throw Exception(
        'MCP invoke of ${req.server}:${req.tool} returned a non-object body',
      );
    }
    return McpInvokeResult.fromJson(data);
  }

  String _url(String path) {
    if (_baseUrl.isEmpty) return path;
    final trimmed =
        _baseUrl.endsWith('/') ? _baseUrl.substring(0, _baseUrl.length - 1) : _baseUrl;
    return '$trimmed$path';
  }
}

class _CachedToken {
  _CachedToken({required this.token, required this.expiresAt});

  final String token;

  /// Wall-clock time when this token expires (issuedAt + ttl).
  final DateTime expiresAt;
}

/// Key on `(server, tool, stable-json-of-input)`. The backend's
/// signature is bound to a hash of the input, so a changed input
/// would invalidate the token anyway — keying on input keeps the
/// cache honest. `jsonEncode` is order-sensitive; that's OK because
/// the same call site reliably builds the same map shape.
String _cacheKey({
  required String server,
  required String tool,
  required Map<String, dynamic> input,
}) {
  return '$server::$tool::${jsonEncode(input)}';
}

String _safeBody(http.Response res) {
  try {
    return res.body;
  } catch (_) {
    return '<no body>';
  }
}
