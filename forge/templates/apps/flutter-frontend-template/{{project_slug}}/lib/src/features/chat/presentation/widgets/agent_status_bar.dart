import 'package:flutter/material.dart';

import '../../domain/agent_state.dart';

class AgentStatusBar extends StatelessWidget {
  const AgentStatusBar({super.key, required this.state});

  final AgentState state;

  @override
  Widget build(BuildContext context) {
    final cost = state.cost;
    final ctx = state.context;
    final todoCount = state.todos.length;
    final usagePct = ctx == null ? 0 : ctx.usagePct.round();

    final theme = Theme.of(context);
    final muted = theme.colorScheme.onSurfaceVariant;

    final children = <Widget>[];
    if (cost != null) {
      children.add(
        _StatusItem(
          label: '\$${cost.totalUsd.toStringAsFixed(4)}',
          tooltip: 'Total cost across all runs',
          color: muted,
        ),
      );
      children.add(
        _StatusItem(
          label: '${_formatTokens(cost.runTokens)} tok',
          tooltip: 'Tokens consumed in current run',
          color: muted,
        ),
      );
    }
    if (todoCount > 0) {
      children.add(
        _StatusItem(
          label: '$todoCount todo${todoCount == 1 ? '' : 's'}',
          tooltip: 'Pending agent todos',
          color: muted,
        ),
      );
    }

    return Container(
      key: const ValueKey('agent-status-bar'),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        border: Border(
          top: BorderSide(color: theme.dividerColor.withValues(alpha: 0.4)),
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Wrap(spacing: 12, children: children),
          if (ctx != null)
            Tooltip(
              message: 'Context window utilization',
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '$usagePct% ctx',
                    style: theme.textTheme.labelSmall?.copyWith(color: muted),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(
                    width: 64,
                    height: 4,
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(2),
                      child: LinearProgressIndicator(
                        value: (usagePct / 100).clamp(0, 1).toDouble(),
                        backgroundColor: theme.dividerColor,
                        color: theme.colorScheme.primary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  String _formatTokens(int n) {
    if (n < 1000) return n.toString();
    if (n < 1000000) return '${(n / 1000).toStringAsFixed(1)}k';
    return '${(n / 1000000).toStringAsFixed(2)}M';
  }
}

class _StatusItem extends StatelessWidget {
  const _StatusItem({required this.label, required this.tooltip, required this.color});
  final String label;
  final String tooltip;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(color: color),
      ),
    );
  }
}
