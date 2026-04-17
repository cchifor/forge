import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../domain/workspace_activity.dart';

class CodeViewerActivity extends StatelessWidget {
  const CodeViewerActivity({super.key, required this.activity});

  final WorkspaceActivity activity;

  @override
  Widget build(BuildContext context) {
    final code = activity.content['code']?.toString() ?? '';
    final language = activity.content['language']?.toString() ?? 'text';
    final filename = activity.content['filename']?.toString();
    final theme = Theme.of(context);

    return Column(
      key: const ValueKey('canvas-code-viewer'),
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: theme.colorScheme.outlineVariant.withValues(alpha: 0.4),
              ),
            ),
          ),
          child: Row(
            children: [
              if (filename != null && filename.isNotEmpty) ...[
                Text(
                  filename,
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                ),
                const SizedBox(width: 8),
              ],
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(3),
                ),
                child: Text(
                  language.toUpperCase(),
                  style: const TextStyle(fontSize: 9),
                ),
              ),
              const Spacer(),
              IconButton(
                tooltip: 'Copy',
                icon: const Icon(Icons.copy, size: 16),
                onPressed: () => Clipboard.setData(ClipboardData(text: code)),
              ),
            ],
          ),
        ),
        Expanded(
          child: Container(
            color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.3),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: SelectableText(
                code,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
