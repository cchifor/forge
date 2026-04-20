import 'package:flutter/material.dart';

/// WorkflowDiagram canvas component — simple DAG of steps with status
/// indicators. Uses a CustomPainter for straight-line edge routing; no
/// external graph-layout package to keep the widget bundle tight.
///
/// Props schema:
/// forge/templates/_shared/canvas-components/WorkflowDiagram.props.schema.json
class WorkflowDiagram extends StatelessWidget {
  final List<_WfNode> nodes;
  final List<_WfEdge> edges;

  WorkflowDiagram({
    super.key,
    required List<Map<String, dynamic>> nodes,
    required List<Map<String, dynamic>> edges,
  })  : nodes = nodes.map(_WfNode.fromMap).toList(growable: false),
        edges = edges.map(_WfEdge.fromMap).toList(growable: false);

  factory WorkflowDiagram.fromProps(Map<String, dynamic> props) => WorkflowDiagram(
        nodes: ((props['nodes'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList(),
        edges: ((props['edges'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList(),
      );

  static const double _nodeW = 160;
  static const double _nodeH = 52;
  static const double _hGap = 32;
  static const double _vGap = 48;

  _Layout _computeLayout() {
    final depth = <String, int>{};
    final incoming = <String, int>{};
    for (final n in nodes) {
      incoming[n.id] = 0;
    }
    for (final e in edges) {
      incoming[e.to] = (incoming[e.to] ?? 0) + 1;
    }
    final queue =
        nodes.where((n) => (incoming[n.id] ?? 0) == 0).map((n) => n.id).toList();
    for (final id in queue) depth[id] = 0;
    while (queue.isNotEmpty) {
      final id = queue.removeAt(0);
      for (final e in edges) {
        if (e.from != id) continue;
        final next = (depth[id] ?? 0) + 1;
        if ((depth[e.to] ?? -1) < next) depth[e.to] = next;
        incoming[e.to] = (incoming[e.to] ?? 0) - 1;
        if ((incoming[e.to] ?? 0) == 0) queue.add(e.to);
      }
    }

    final byDepth = <int, List<String>>{};
    for (final n in nodes) {
      byDepth.putIfAbsent(depth[n.id] ?? 0, () => []).add(n.id);
    }

    final positions = <String, Offset>{};
    final maxCols =
        byDepth.values.map((a) => a.length).fold<int>(1, (p, c) => p > c ? p : c);
    for (final entry in byDepth.entries) {
      final d = entry.key;
      final ids = entry.value;
      final rowW = ids.length * _nodeW + (ids.length - 1) * _hGap;
      final startX = ((maxCols * _nodeW + (maxCols - 1) * _hGap) - rowW) / 2;
      for (var i = 0; i < ids.length; i++) {
        positions[ids[i]] = Offset(
          startX + i * (_nodeW + _hGap),
          d * (_nodeH + _vGap),
        );
      }
    }

    final width = maxCols * _nodeW + (maxCols - 1) * _hGap;
    final height = ((byDepth.length == 0 ? 1 : byDepth.length) - 1) * (_nodeH + _vGap) + _nodeH;
    return _Layout(positions: positions, width: width, height: height);
  }

  @override
  Widget build(BuildContext context) {
    final layout = _computeLayout();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 600),
          child: InteractiveViewer(
            child: SizedBox(
              width: layout.width,
              height: layout.height,
              child: CustomPaint(
                painter: _WfPainter(
                  nodes: nodes,
                  edges: edges,
                  positions: layout.positions,
                  nodeW: _nodeW,
                  nodeH: _nodeH,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _WfNode {
  final String id;
  final String label;
  final String status;

  const _WfNode({required this.id, required this.label, required this.status});

  factory _WfNode.fromMap(Map<String, dynamic> raw) => _WfNode(
        id: raw['id'] as String,
        label: raw['label'] as String,
        status: raw['status'] as String,
      );
}

class _WfEdge {
  final String from;
  final String to;

  const _WfEdge({required this.from, required this.to});

  factory _WfEdge.fromMap(Map<String, dynamic> raw) => _WfEdge(
        from: raw['from'] as String,
        to: raw['to'] as String,
      );
}

class _Layout {
  final Map<String, Offset> positions;
  final double width;
  final double height;

  const _Layout({required this.positions, required this.width, required this.height});
}

class _WfPainter extends CustomPainter {
  final List<_WfNode> nodes;
  final List<_WfEdge> edges;
  final Map<String, Offset> positions;
  final double nodeW;
  final double nodeH;

  _WfPainter({
    required this.nodes,
    required this.edges,
    required this.positions,
    required this.nodeW,
    required this.nodeH,
  });

  Color _fill(String status) {
    switch (status) {
      case 'running':
        return const Color(0xFFFEF3C7);
      case 'completed':
        return const Color(0xFFDCFCE7);
      case 'error':
        return const Color(0xFFFEE2E2);
      case 'skipped':
        return const Color(0xFFE5E7EB);
      default:
        return const Color(0xFFF3F4F6);
    }
  }

  Color _stroke(String status) {
    switch (status) {
      case 'running':
        return const Color(0xFFD97706);
      case 'completed':
        return const Color(0xFF16A34A);
      case 'error':
        return const Color(0xFFDC2626);
      case 'skipped':
        return const Color(0xFF6B7280);
      default:
        return const Color(0xFF9CA3AF);
    }
  }

  String _icon(String status) {
    switch (status) {
      case 'running':
        return '◐';
      case 'completed':
        return '●';
      case 'error':
        return '✕';
      case 'skipped':
        return '↳';
      default:
        return '○';
    }
  }

  @override
  void paint(Canvas canvas, Size size) {
    final edgePaint = Paint()
      ..color = const Color(0xFF9CA3AF)
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;

    for (final edge in edges) {
      final from = positions[edge.from];
      final to = positions[edge.to];
      if (from == null || to == null) continue;
      final start = Offset(from.dx + nodeW / 2, from.dy + nodeH);
      final end = Offset(to.dx + nodeW / 2, to.dy);
      canvas.drawLine(start, end, edgePaint);
      _drawArrowHead(canvas, end, start, edgePaint);
    }

    for (final node in nodes) {
      final pos = positions[node.id];
      if (pos == null) continue;
      final rect = Rect.fromLTWH(pos.dx, pos.dy, nodeW, nodeH);
      final rrect = RRect.fromRectAndRadius(rect, const Radius.circular(8));
      canvas.drawRRect(
        rrect,
        Paint()..color = _fill(node.status),
      );
      canvas.drawRRect(
        rrect,
        Paint()
          ..color = _stroke(node.status)
          ..strokeWidth = 1.5
          ..style = PaintingStyle.stroke,
      );

      final text = TextSpan(
        text: '${_icon(node.status)} ${node.label}',
        style: const TextStyle(
          fontSize: 13,
          color: Color(0xFF111827),
          fontFamilyFallback: ['Segoe UI Emoji', 'Apple Color Emoji'],
        ),
      );
      final tp = TextPainter(
        text: text,
        textAlign: TextAlign.center,
        textDirection: TextDirection.ltr,
        maxLines: 2,
        ellipsis: '...',
      )..layout(maxWidth: nodeW - 16);
      final offset = Offset(
        pos.dx + (nodeW - tp.width) / 2,
        pos.dy + (nodeH - tp.height) / 2,
      );
      tp.paint(canvas, offset);
    }
  }

  void _drawArrowHead(Canvas canvas, Offset tip, Offset from, Paint paint) {
    final dx = tip.dx - from.dx;
    final dy = tip.dy - from.dy;
    final len = (dx * dx + dy * dy).abs();
    if (len == 0) return;
    final angle = dy == 0 && dx == 0 ? 0.0 : -0.3;
    const size = 6.0;
    // Simple triangular arrowhead pointing into `tip`.
    final path = Path()
      ..moveTo(tip.dx - size, tip.dy - size)
      ..lineTo(tip.dx, tip.dy)
      ..lineTo(tip.dx - size, tip.dy + size);
    canvas.drawPath(
      path,
      Paint()
        ..color = paint.color
        ..strokeWidth = paint.strokeWidth
        ..style = PaintingStyle.stroke,
    );
    // Silence unused-variable warnings for the angle / len computations
    // kept for future curve routing.
    if (angle < -1 || len < -1) debugPrint('');
  }

  @override
  bool shouldRepaint(_WfPainter oldDelegate) =>
      nodes != oldDelegate.nodes || edges != oldDelegate.edges;
}
