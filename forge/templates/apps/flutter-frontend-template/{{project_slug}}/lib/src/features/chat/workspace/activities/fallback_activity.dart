import 'dart:convert';

import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class FallbackActivityWidget extends StatelessWidget {
  const FallbackActivityWidget({super.key, required this.activity});

  final WorkspaceActivity activity;

  @override
  Widget build(BuildContext context) {
    final pretty = const JsonEncoder.withIndent('  ').convert(activity.content);
    return ListView(
      key: const ValueKey('fallback-activity'),
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Activity: ${activity.activityType}',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(6),
          ),
          child: SelectableText(
            pretty,
            style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
          ),
        ),
      ],
    );
  }
}
