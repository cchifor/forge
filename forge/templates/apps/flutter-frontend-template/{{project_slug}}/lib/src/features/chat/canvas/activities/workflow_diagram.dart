import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

/// "Minimum viable" workflow diagram — a horizontal node chain with status
/// chips and a collapsible edge list. Full Mermaid-style rendering would mean
/// shipping a Dart parser + custom layout, which is deferred.
class WorkflowDiagramActivity extends StatelessWidget {
  const WorkflowDiagramActivity({super.key, required this.activity});

  final WorkspaceActivity activity;

  List<Map<String, dynamic>> get _nodes {
    final raw = activity.content['nodes'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  List<Map<String, dynamic>> get _edges {
    final raw = activity.content['edges'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  Color _statusColor(BuildContext context, String? status) {
    final scheme = Theme.of(context).colorScheme;
    switch (status) {
      case 'done':
        return scheme.primary;
      case 'running':
        return scheme.tertiary;
      case 'error':
        return scheme.error;
      default:
        return scheme.outline;
    }
  }

  @override
  Widget build(BuildContext context) {
    final nodes = _nodes;
    final edges = _edges;
    return ListView(
      key: const ValueKey('canvas-workflow'),
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Workflow (${nodes.length} nodes, ${edges.length} edges)',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            for (var i = 0; i < nodes.length; i++) ...[
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: _statusColor(context, nodes[i]['status']?.toString())
                      .withValues(alpha: 0.15),
                  border: Border.all(
                    color: _statusColor(context, nodes[i]['status']?.toString())
                        .withValues(alpha: 0.5),
                  ),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(nodes[i]['label']?.toString() ?? ''),
              ),
              if (i < nodes.length - 1)
                Icon(Icons.arrow_forward,
                    size: 16, color: Theme.of(context).colorScheme.outline),
            ],
          ],
        ),
        if (edges.isNotEmpty) ...[
          const SizedBox(height: 12),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Edges', style: Theme.of(context).textTheme.bodySmall),
            children: [
              for (final e in edges)
                ListTile(
                  dense: true,
                  title: Text(
                    '${e['from']} → ${e['to']}',
                    style: const TextStyle(fontFamily: 'monospace'),
                  ),
                ),
            ],
          ),
        ],
      ],
    );
  }
}
