// MCP client-side hook — caches tool registry + enforces approval mode.
//
// Pairs with lib/src/features/mcp/tool_registry.dart + approval_dialog.dart.
// Callers construct one McpClient per app, hand the BuildContext of the
// requesting surface to `invoke` so the approval dialog can render above it.

import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;

import 'approval_dialog.dart';
import 'tool_registry.dart';

class McpClient {
  final Uri baseUrl;
  final http.Client _http;
  final Map<String, bool> _sessionApprovals = {};
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

    final response = await _http.post(
      baseUrl.resolve('/mcp/invoke'),
      headers: {'content-type': 'application/json'},
      body: jsonEncode({'server': server, 'tool': tool, 'input': input}),
    );
    if (response.statusCode != 200) {
      throw Exception('POST /mcp/invoke ${response.statusCode}');
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    if (payload['ok'] != true) {
      throw Exception(payload['error']?.toString() ?? 'MCP invoke failed');
    }
    return payload['output'];
  }
}
