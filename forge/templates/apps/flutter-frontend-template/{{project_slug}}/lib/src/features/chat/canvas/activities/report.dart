import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../../domain/workspace_activity.dart';

class ReportActivity extends StatelessWidget {
  const ReportActivity({super.key, required this.activity});

  final WorkspaceActivity activity;

  @override
  Widget build(BuildContext context) {
    final title = activity.content['title']?.toString();
    final markdown = (activity.content['markdown'] ??
            activity.content['body'] ??
            '')
        .toString();

    return ListView(
      key: const ValueKey('canvas-report'),
      padding: const EdgeInsets.all(16),
      children: [
        if (title != null && title.isNotEmpty) ...[
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
        ],
        MarkdownBody(data: markdown, selectable: true),
      ],
    );
  }
}
