import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../domain/workspace_activity.dart';
import '../presentation/chat_providers.dart';
import 'engines/ag_ui_engine.dart';
import 'engines/mcp_ext_engine.dart';
import 'workspace_registry.dart';

class WorkspacePane extends ConsumerWidget {
  const WorkspacePane({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activity =
        ref.watch(chatProvider.select((s) => s.workspaceActivity));
    if (activity == null) return const SizedBox.shrink();
    final entry = WorkspaceRegistry.resolve(activity.activityType);
    final theme = Theme.of(context);

    return Column(
      key: const ValueKey('workspace-pane'),
      children: [
        Container(
          height: 48,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: theme.colorScheme.outlineVariant.withValues(alpha: 0.4),
              ),
            ),
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(entry.label, style: theme.textTheme.titleSmall),
              ),
              IconButton(
                tooltip: 'Close',
                icon: const Icon(Icons.close, size: 18),
                onPressed: () =>
                    ref.read(chatProvider.notifier).clearWorkspaceActivity(),
              ),
            ],
          ),
        ),
        Expanded(
          child: activity.engine == AgentEngine.mcpExt
              ? McpExtEngine(activity: activity, onAction: (a) => _dispatch(ref, a))
              : AgUiEngine(activity: activity, onAction: (a) => _dispatch(ref, a)),
        ),
      ],
    );
  }

  void _dispatch(WidgetRef ref, WorkspaceAction action) {
    if (action.type == 'submit') {
      // Workspace submissions resume the agent as a HITL response.
      final notifier = ref.read(chatProvider.notifier);
      // Encode the action data as the answer payload — backend interprets it.
      notifier.respondToPrompt(action.data['answer']?.toString() ??
          action.data['decision']?.toString() ??
          action.data.toString());
    }
  }
}
