import 'package:flutter/material.dart';

import '../../domain/tool_call_info.dart';

/// Tool-call chip with a collapsible args preview (Pillar G.2).
///
/// The chip itself mirrors Vue/Svelte's ``ToolCallStatus`` UI; the
/// expansion tile below it shows the streamed TOOL_CALL_ARGS buffer
/// (newlines stripped while running) and the pretty-printed JSON on
/// completion. Default-collapsed so the message column stays compact
/// when there are many tool calls.
class ToolCallStatusChip extends StatelessWidget {
  const ToolCallStatusChip({super.key, required this.toolCall});

  final ToolCallInfo toolCall;

  /// The text to render inside the expansion tile body. ``argsPretty``
  /// wins once set (TOOL_CALL_END); otherwise the raw ``argsBuffer``
  /// with embedded newlines stripped — long partial JSONs mid-stream
  /// shouldn't push the preview taller than necessary.
  String? get _displayArgs {
    final pretty = toolCall.argsPretty;
    if (pretty != null && pretty.isNotEmpty) return pretty;
    final buffer = toolCall.argsBuffer;
    if (buffer != null && buffer.isNotEmpty) {
      return buffer.replaceAll(RegExp(r'\n+'), ' ');
    }
    return null;
  }

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

    final header = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        iconWidget,
        const SizedBox(width: 6),
        Text(
          toolCall.name,
          style: Theme.of(context).textTheme.labelSmall?.copyWith(color: fg),
        ),
      ],
    );

    final args = _displayArgs;
    if (args == null) {
      // No args yet (or none ever) — render the bare chip, matching the
      // pre-G.2 layout so chips without args don't grow a useless
      // expander.
      return Container(
        key: ValueKey('tool-call-${toolCall.id}'),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: fg.withValues(alpha: 0.4)),
        ),
        child: header,
      );
    }

    // ExpansionTile is the Material-native equivalent of HTML
    // ``<details>``. Cross-stack consistency with Vue/Svelte's
    // collapsible preview.
    return Container(
      key: ValueKey('tool-call-${toolCall.id}'),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: fg.withValues(alpha: 0.4)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          key: ValueKey('tool-call-args-${toolCall.id}'),
          tilePadding: const EdgeInsets.symmetric(horizontal: 8),
          minTileHeight: 0,
          dense: true,
          title: header,
          childrenPadding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
          expandedAlignment: Alignment.centerLeft,
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              constraints: const BoxConstraints(maxHeight: 192),
              decoration: BoxDecoration(
                color: scheme.surface.withValues(alpha: 0.4),
                borderRadius: BorderRadius.circular(4),
              ),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              width: double.infinity,
              child: SingleChildScrollView(
                child: SelectableText(
                  args,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        fontFamily: 'monospace',
                        color: fg,
                      ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
