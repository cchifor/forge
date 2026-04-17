import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../chat_constants.dart';
import 'chat_context_toggle.dart';
import 'chat_input_bar.dart';
import 'chat_message_list.dart';
import 'chat_providers.dart';
import 'widgets/agent_status_bar.dart';

class ChatPanel extends ConsumerWidget {
  const ChatPanel({this.isFullScreen = false, super.key});

  final bool isFullScreen;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final agentState = ref.watch(chatProvider.select((s) => s.agentState));

    return ColoredBox(
      color: theme.colorScheme.surface,
      child: Column(
        children: [
          const _ChatHeader(),
          const ChatContextToggle(),
          const Expanded(child: ChatMessageList()),
          AgentStatusBar(state: agentState),
          const ChatInputBar(),
        ],
      ),
    );
  }
}

class _ChatHeader extends ConsumerWidget {
  const _ChatHeader();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final model = ref.watch(chatModelProvider);
    final approval = ref.watch(chatApprovalProvider);
    final theme = Theme.of(context);

    return Container(
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
          DropdownButton<String>(
            value: model,
            isDense: true,
            underline: const SizedBox.shrink(),
            items: [
              for (final m in availableModels)
                DropdownMenuItem(value: m.id, child: Text(m.label)),
            ],
            onChanged: (v) {
              if (v != null) ref.read(chatModelProvider.notifier).set(v);
            },
          ),
          const SizedBox(width: 12),
          DropdownButton<ApprovalMode>(
            value: approval,
            isDense: true,
            underline: const SizedBox.shrink(),
            items: [
              for (final mode in ApprovalMode.values)
                DropdownMenuItem(value: mode, child: Text(mode.label)),
            ],
            onChanged: (v) {
              if (v != null) ref.read(chatApprovalProvider.notifier).set(v);
            },
          ),
          const Spacer(),
          IconButton(
            tooltip: 'New thread',
            onPressed: () => ref.read(chatProvider.notifier).resetThread(),
            icon: const Icon(Icons.refresh, size: 18),
          ),
        ],
      ),
    );
  }
}
