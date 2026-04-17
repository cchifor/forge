import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class ApprovalReviewActivity extends StatelessWidget {
  const ApprovalReviewActivity({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction action)? onAction;

  List<String> get _items {
    final raw = activity.content['items'];
    if (raw is List) return raw.map((e) => e.toString()).toList();
    return const [];
  }

  void _decide(String decision) {
    onAction?.call(WorkspaceAction(type: 'submit', data: {'decision': decision}));
  }

  @override
  Widget build(BuildContext context) {
    final summary = activity.content['summary']?.toString();
    final diff = activity.content['diff']?.toString();
    final theme = Theme.of(context);

    return ListView(
      key: const ValueKey('approval-review'),
      padding: const EdgeInsets.all(16),
      children: [
        Text('Review & approve', style: theme.textTheme.titleSmall),
        if (summary != null && summary.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(summary, style: theme.textTheme.bodyMedium),
        ],
        if (_items.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final item in _items)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.fiber_manual_record, size: 8),
                  const SizedBox(width: 6),
                  Expanded(child: Text(item)),
                ],
              ),
            ),
        ],
        if (diff != null && diff.isNotEmpty) ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(6),
            ),
            child: SelectableText(
              diff,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ],
        const SizedBox(height: 16),
        Wrap(
          spacing: 8,
          children: [
            FilledButton(
              key: const ValueKey('approve-button'),
              onPressed: () => _decide('approve'),
              child: const Text('Approve'),
            ),
            OutlinedButton(
              key: const ValueKey('reject-button'),
              onPressed: () => _decide('reject'),
              child: const Text('Reject'),
            ),
          ],
        ),
      ],
    );
  }
}
