import 'dart:convert';

import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';

class CanvasFallback extends StatelessWidget {
  const CanvasFallback({super.key, required this.activity});

  final WorkspaceActivity activity;

  @override
  Widget build(BuildContext context) {
    final pretty = const JsonEncoder.withIndent('  ').convert(activity.content);
    return ListView(
      key: const ValueKey('canvas-fallback'),
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Canvas activity: ${activity.activityType}',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 8),
        SelectableText(
          pretty,
          style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
        ),
      ],
    );
  }
}
