import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';
import '../workspace_registry.dart';

class AgUiEngine extends StatelessWidget {
  const AgUiEngine({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction action)? onAction;

  @override
  Widget build(BuildContext context) {
    final entry = WorkspaceRegistry.resolve(activity.activityType);
    return entry.builder(context, activity, onAction);
  }
}
