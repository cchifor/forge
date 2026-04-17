import 'package:flutter/material.dart';

import '../../domain/tool_call_info.dart';

class ToolCallStatusChip extends StatelessWidget {
  const ToolCallStatusChip({super.key, required this.toolCall});

  final ToolCallInfo toolCall;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (Color bg, Color fg, IconData icon, bool spin) = switch (toolCall.status) {
      ToolCallStatus.completed => (
          scheme.primary.withValues(alpha: 0.12),
          scheme.primary,
          Icons.check_circle_outline,
          false,
        ),
      ToolCallStatus.error => (
          scheme.error.withValues(alpha: 0.12),
          scheme.error,
          Icons.error_outline,
          false,
        ),
      ToolCallStatus.running => (
          scheme.tertiary.withValues(alpha: 0.12),
          scheme.tertiary,
          Icons.sync,
          true,
        ),
    };

    Widget iconWidget = Icon(icon, size: 12, color: fg);
    if (spin) {
      iconWidget = SizedBox(
        width: 12,
        height: 12,
        child: CircularProgressIndicator(strokeWidth: 1.5, color: fg),
      );
    }

    return Container(
      key: ValueKey('tool-call-${toolCall.id}'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: fg.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          iconWidget,
          const SizedBox(width: 6),
          Text(
            toolCall.name,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(color: fg),
          ),
        ],
      ),
    );
  }
}
