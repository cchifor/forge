// MCP tool discovery panel (Flutter scaffold for Phase 3.4).
//
// Fetches GET /mcp/tools and renders each tool with its server badge
// + approval-mode indicator.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

class McpTool {
  final String server;
  final String name;
  final String description;
  final Map<String, dynamic> inputSchema;
  final String approvalMode;

  const McpTool({
    required this.server,
    required this.name,
    required this.description,
    required this.inputSchema,
    required this.approvalMode,
  });

  factory McpTool.fromJson(Map<String, dynamic> json) => McpTool(
        server: json['server'] as String,
        name: json['name'] as String,
        description: json['description'] as String? ?? '',
        inputSchema: (json['input_schema'] as Map<String, dynamic>?) ?? const {},
        approvalMode: json['approval_mode'] as String? ?? 'prompt-once',
      );
}

class ToolRegistry extends StatefulWidget {
  final Uri baseUrl;
  final void Function(McpTool tool)? onInvoke;

  const ToolRegistry({super.key, required this.baseUrl, this.onInvoke});

  @override
  State<ToolRegistry> createState() => _ToolRegistryState();
}

class _ToolRegistryState extends State<ToolRegistry> {
  late Future<List<McpTool>> _future;

  @override
  void initState() {
    super.initState();
    _future = _fetchTools();
  }

  Future<List<McpTool>> _fetchTools() async {
    final response = await http.get(widget.baseUrl.resolve('/mcp/tools'));
    if (response.statusCode != 200) {
      throw Exception('GET /mcp/tools ${response.statusCode}');
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! List) {
      throw Exception('expected list, got ${decoded.runtimeType}');
    }
    return decoded
        .whereType<Map<String, dynamic>>()
        .map(McpTool.fromJson)
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<McpTool>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(child: Text('Failed to load tools: ${snapshot.error}'));
        }
        final tools = snapshot.data ?? const <McpTool>[];
        if (tools.isEmpty) {
          return const Padding(
            padding: EdgeInsets.all(16),
            child: Text('No MCP servers configured. See mcp.config.json.'),
          );
        }
        return ListView.separated(
          itemCount: tools.length,
          separatorBuilder: (_, __) => const Divider(height: 1),
          itemBuilder: (context, i) {
            final tool = tools[i];
            return ListTile(
              title: Row(
                children: [
                  _ServerBadge(label: tool.server),
                  const SizedBox(width: 8),
                  Expanded(child: Text(tool.name, style: const TextStyle(fontWeight: FontWeight.bold))),
                  _ApprovalModeChip(mode: tool.approvalMode),
                ],
              ),
              subtitle: Text(tool.description),
              onTap: widget.onInvoke == null ? null : () => widget.onInvoke!(tool),
            );
          },
        );
      },
    );
  }
}

class _ServerBadge extends StatelessWidget {
  final String label;
  const _ServerBadge({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(label, style: const TextStyle(fontSize: 11)),
    );
  }
}

class _ApprovalModeChip extends StatelessWidget {
  final String mode;
  const _ApprovalModeChip({required this.mode});

  Color _bg(BuildContext context) {
    switch (mode) {
      case 'auto':
        return Colors.green.shade100;
      case 'prompt-every':
        return Colors.red.shade100;
      default:
        return Colors.amber.shade100;
    }
  }

  Color _fg() {
    switch (mode) {
      case 'auto':
        return const Color(0xFF166534);
      case 'prompt-every':
        return const Color(0xFF991B1B);
      default:
        return const Color(0xFF854D0E);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(color: _bg(context), borderRadius: BorderRadius.circular(4)),
      child: Text(mode, style: TextStyle(color: _fg(), fontSize: 10)),
    );
  }
}
