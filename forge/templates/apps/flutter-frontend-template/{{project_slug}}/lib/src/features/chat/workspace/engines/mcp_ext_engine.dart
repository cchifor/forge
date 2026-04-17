import 'package:flutter/material.dart';

import '../../domain/workspace_activity.dart';
import '../workspace_registry.dart';

/// MCP activities render natively (no iframe sandbox) — Flutter has no DOM.
/// The engine layer exists so MCP-specific dispatch (e.g. POSTing tool results
/// back to the agent) can be added without touching activity widgets.
class McpExtEngine extends StatelessWidget {
  const McpExtEngine({super.key, required this.activity, this.onAction});

  final WorkspaceActivity activity;
  final void Function(WorkspaceAction action)? onAction;

  @override
  Widget build(BuildContext context) {
    final entry = WorkspaceRegistry.resolve(activity.activityType);
    return entry.builder(context, activity, onAction);
  }
}
