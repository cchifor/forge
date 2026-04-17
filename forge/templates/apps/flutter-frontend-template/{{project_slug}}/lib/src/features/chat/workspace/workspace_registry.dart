import 'package:flutter/widgets.dart';

import '../domain/workspace_activity.dart';
import 'activities/approval_review.dart';
import 'activities/credential_form.dart';
import 'activities/fallback_activity.dart';
import 'activities/file_explorer.dart';
import 'activities/user_prompt_review.dart';

typedef ActivityBuilder = Widget Function(
  BuildContext context,
  WorkspaceActivity activity,
  void Function(WorkspaceAction action)? onAction,
);

class WorkspaceRegistryEntry {
  const WorkspaceRegistryEntry({required this.builder, required this.label});
  final ActivityBuilder builder;
  final String label;
}

class WorkspaceRegistry {
  WorkspaceRegistry._();

  static final Map<String, WorkspaceRegistryEntry> _entries = {
    'credential_form': WorkspaceRegistryEntry(
      label: 'Credential Form',
      builder: (ctx, a, onAction) => CredentialFormActivity(activity: a, onAction: onAction),
    ),
    'file_explorer': WorkspaceRegistryEntry(
      label: 'File Explorer',
      builder: (ctx, a, onAction) => FileExplorerActivity(activity: a, onAction: onAction),
    ),
    'approval_review': WorkspaceRegistryEntry(
      label: 'Review & Approve',
      builder: (ctx, a, onAction) => ApprovalReviewActivity(activity: a, onAction: onAction),
    ),
    'user_prompt': WorkspaceRegistryEntry(
      label: 'Question',
      builder: (ctx, a, onAction) => UserPromptReviewActivity(activity: a, onAction: onAction),
    ),
    'fallback': WorkspaceRegistryEntry(
      label: 'Activity',
      builder: (ctx, a, onAction) => FallbackActivityWidget(activity: a),
    ),
  };

  static void register(String activityType, WorkspaceRegistryEntry entry) {
    _entries[activityType] = entry;
  }

  static WorkspaceRegistryEntry resolve(String activityType) {
    return _entries[activityType] ?? _entries['fallback']!;
  }
}
