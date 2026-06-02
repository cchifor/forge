/// Test the wire-protocol bug fix end-to-end against a mocked backend.
///
/// Mirrors the TS suite at
/// `packages/canvas-core/tests/mcp_approval_client.test.ts` so the two
/// stacks have parity coverage on the Python MCP router contract.
/// The Python backend at
/// `forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py`
/// 401s on `/mcp/invoke` when `approval_mode != "auto"` and the
/// `approval_token` is missing/invalid. This test fakes that backend
/// and verifies the client mints + presents the token correctly.

import 'dart:convert';

import 'package:forge_canvas_core/forge_canvas_core.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

class _FakeServer {
  _FakeServer({Set<String>? knownTokens})
      : knownTokens = knownTokens ?? <String>{};

  final List<String> mintedTokens = [];
  final List<_InvokeCall> invokeCalls = [];
  final Set<String> knownTokens;

  /// Force the next mint to a non-2xx status.
  int? failMint;

  /// Force the next invoke to a 401.
  bool failInvokeWith401Once = false;

  late final http.Client client = MockClient((req) async {
    final url = req.url.toString();
    if (url.endsWith('/mcp/approval/mint')) {
      if (failMint != null) {
        final status = failMint!;
        return http.Response('mint failed: $status', status);
      }
      final token = 'token-${mintedTokens.length + 1}';
      mintedTokens.add(token);
      knownTokens.add(token);
      return http.Response(
        jsonEncode({'token': token}),
        200,
        headers: {'content-type': 'application/json'},
      );
    }
    if (url.endsWith('/mcp/invoke')) {
      final body = jsonDecode(req.body) as Map<String, dynamic>;
      final tokenSeen = body['approval_token'] as String?;
      invokeCalls.add(_InvokeCall(body: body, tokenSeen: tokenSeen));
      if (failInvokeWith401Once) {
        failInvokeWith401Once = false;
        return http.Response(
          'Approval token missing or invalid. Call /mcp/approval/mint first.',
          401,
        );
      }
      // auto path: no token required → accept.
      if (tokenSeen == null) {
        return http.Response(
          jsonEncode({'ok': true, 'output': 'auto-ok'}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (!knownTokens.contains(tokenSeen)) {
        return http.Response(
          'Approval token missing or invalid. Call /mcp/approval/mint first.',
          401,
        );
      }
      return http.Response(
        jsonEncode({'ok': true, 'output': 'gated-ok'}),
        200,
        headers: {'content-type': 'application/json'},
      );
    }
    return http.Response('not found', 404);
  });
}

class _InvokeCall {
  _InvokeCall({required this.body, required this.tokenSeen});

  final Map<String, dynamic> body;
  final String? tokenSeen;
}

McpInvokeRequest _baseReq() => McpInvokeRequest(
      server: 'filesystem',
      tool: 'read_file',
      input: const {'path': '/etc/hosts'},
      approvalMode: ApprovalMode.promptOnce,
    );

void main() {
  group('McpApprovalClient — wire-bug fix', () {
    late _FakeServer server;
    late DateTime now;

    setUp(() {
      server = _FakeServer();
      now = DateTime.utc(2026, 1, 1);
    });

    test('auto mode skips mint and invokes directly', () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      final result = await client.invoke(
        McpInvokeRequest(
          server: 'filesystem',
          tool: 'read_file',
          input: const {'path': '/etc/hosts'},
          approvalMode: ApprovalMode.auto,
        ),
      );
      expect(result.ok, isTrue);
      expect(result.output, 'auto-ok');
      expect(server.mintedTokens, isEmpty);
      expect(server.invokeCalls, hasLength(1));
      expect(server.invokeCalls.first.tokenSeen, isNull);
    });

    test('non-auto mode mints, then invokes with the token (THE bug fix)',
        () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      final result = await client.invoke(_baseReq());
      expect(result.ok, isTrue);
      expect(result.output, 'gated-ok');
      expect(server.mintedTokens, hasLength(1));
      expect(server.invokeCalls, hasLength(1));
      expect(server.invokeCalls.first.tokenSeen, server.mintedTokens.first);
    });

    test('caches the token across invocations of the same tuple', () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      await client.invoke(_baseReq());
      await client.invoke(_baseReq());
      expect(server.mintedTokens, hasLength(1));
      expect(server.invokeCalls, hasLength(2));
      expect(
        server.invokeCalls.map((c) => c.tokenSeen),
        [server.mintedTokens.first, server.mintedTokens.first],
      );
    });

    test('re-mints when the input payload changes', () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      await client.invoke(_baseReq());
      await client.invoke(
        McpInvokeRequest(
          server: 'filesystem',
          tool: 'read_file',
          input: const {'path': '/etc/passwd'},
          approvalMode: ApprovalMode.promptOnce,
        ),
      );
      expect(server.mintedTokens, hasLength(2));
    });

    test('re-mints after token TTL expires', () async {
      final client = McpApprovalClient(
        httpClient: server.client,
        now: () => now,
        tokenTtl: const Duration(seconds: 1),
      );
      await client.invoke(_baseReq());
      now = now.add(const Duration(seconds: 2));
      await client.invoke(_baseReq());
      expect(server.mintedTokens, hasLength(2));
    });

    test('raises McpApprovalRejected on 401 + evicts the cached token',
        () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      // Prime cache with a valid token.
      await client.invoke(_baseReq());
      expect(server.mintedTokens, hasLength(1));

      // Now force the next invoke to 401 (e.g. backend rotated its
      // secret). Await the rejection inline so the eviction completes
      // before we re-invoke.
      server.failInvokeWith401Once = true;
      await expectLater(
        client.invoke(_baseReq()),
        throwsA(isA<McpApprovalRejected>()),
      );

      // The cache should have been evicted; next invoke re-mints.
      await client.invoke(_baseReq());
      expect(server.mintedTokens, hasLength(2));
    });

    test('surfaces clear error when mint endpoint returns 404', () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      server.failMint = 404;
      await expectLater(
        client.invoke(_baseReq()),
        throwsA(
          predicate(
            (Object? e) =>
                e is Exception &&
                e.toString().contains('Failed to mint MCP approval token'),
          ),
        ),
      );
    });

    test('honours custom baseUrl', () async {
      // The fake server's dispatch keys on `endsWith('/mcp/approval/mint')`
      // / `endsWith('/mcp/invoke')`, so it already accepts both the
      // bare-path form and the absolute-URL form the baseUrl test
      // produces. Re-use it directly through a thin URL-recording shim.
      final visited = <String>[];
      final wrappedClient = MockClient((req) async {
        visited.add(req.url.toString());
        return server.client.send(req).then(http.Response.fromStream);
      });
      final client = McpApprovalClient(
        httpClient: wrappedClient,
        now: () => now,
        baseUrl: 'https://api.example.test/api',
      );
      await client.invoke(_baseReq());
      expect(visited, contains('https://api.example.test/api/mcp/approval/mint'));
      expect(visited, contains('https://api.example.test/api/mcp/invoke'));
    });

    test('evict() forces a re-mint on next invoke', () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      final req = _baseReq();
      await client.invoke(req);
      client.evict(server: req.server, tool: req.tool, input: req.input);
      await client.invoke(req);
      expect(server.mintedTokens, hasLength(2));
    });

    test('clearCache() drops all tokens', () async {
      final client = McpApprovalClient(httpClient: server.client, now: () => now);
      await client.invoke(_baseReq());
      await client.invoke(
        McpInvokeRequest(
          server: 'filesystem',
          tool: 'other',
          input: const {'path': '/etc/hosts'},
          approvalMode: ApprovalMode.promptOnce,
        ),
      );
      client.clearCache();
      await client.invoke(_baseReq());
      expect(server.mintedTokens, hasLength(3));
    });
  });

  group('McpApprovalClient — McpApprovalRejected', () {
    test('exposes structured fields', () {
      final err = McpApprovalRejected(
        server: 'filesystem',
        tool: 'read_file',
        status: 401,
        detail: 'token expired',
      );
      expect(err.name, 'McpApprovalRejected');
      expect(err.server, 'filesystem');
      expect(err.tool, 'read_file');
      expect(err.status, 401);
      expect(err.detail, 'token expired');
      expect(err.toString(), contains('rejected with status 401'));
    });

    test('propagates fetch failures unchanged', () async {
      final brokenClient = MockClient((req) async {
        throw const _NetworkDown();
      });
      final client = McpApprovalClient(httpClient: brokenClient);
      await expectLater(
        client.invoke(_baseReq()),
        throwsA(isA<_NetworkDown>()),
      );
    });
  });
}

class _NetworkDown implements Exception {
  const _NetworkDown();
  @override
  String toString() => 'network down';
}
