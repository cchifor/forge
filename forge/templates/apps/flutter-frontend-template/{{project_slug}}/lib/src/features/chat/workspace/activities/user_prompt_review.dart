import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class UserPromptReviewActivity extends StatelessWidget {
  const UserPromptReviewActivity({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction action)? onAction;

  List<Map<String, dynamic>> get _options {
    final raw = activity.content['options'];
    if (raw is List) {
      return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  @override
  Widget build(BuildContext context) {
    final question = activity.content['question']?.toString() ?? 'Question';
    return ListView(
      key: const ValueKey('user-prompt-review'),
      padding: const EdgeInsets.all(16),
      children: [
        Text(question, style: Theme.of(context).textTheme.bodyLarge),
        const SizedBox(height: 12),
        for (final opt in _options)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: OutlinedButton(
              onPressed: () => onAction?.call(
                WorkspaceAction(
                  type: 'submit',
                  data: {'answer': opt['label']?.toString() ?? ''},
                ),
              ),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(opt['label']?.toString() ?? ''),
                    if (opt['description'] != null)
                      Text(
                        opt['description'].toString(),
                        style: Theme.of(context).textTheme.labelSmall,
                      ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}
