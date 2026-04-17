import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../theme/design_tokens.dart';
import 'chat_providers.dart';
import 'widgets/chat_message_bubble.dart';
import 'widgets/user_prompt_card.dart';

class ChatMessageList extends ConsumerWidget {
  const ChatMessageList({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final messages = ref.watch(chatMessagesProvider);
    final pendingPrompt = ref.watch(chatPendingPromptProvider);
    final isRunning = ref.watch(chatIsRunningProvider);
    final error = ref.watch(chatErrorProvider);
    final activeToolCalls =
        ref.watch(chatProvider.select((s) => s.activeToolCalls));

    if (messages.isEmpty && pendingPrompt == null && error == null) {
      return Center(
        key: const ValueKey('chat-empty-state'),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.auto_awesome,
              size: 32,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 12),
            const Text('How can I help?', style: TextStyle(fontSize: 14)),
            const SizedBox(height: 4),
            Text(
              'Ask a question or describe what you need.',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ),
      );
    }

    final children = <Widget>[
      for (var i = 0; i < messages.length; i++)
        ChatMessageBubble(
          message: messages[i],
          toolCalls: i == messages.length - 1 ? activeToolCalls : const [],
        ),
      if (pendingPrompt != null)
        UserPromptCard(
          prompt: pendingPrompt,
          onRespond: (answer) =>
              ref.read(chatProvider.notifier).respondToPrompt(answer),
        ),
      if (error != null)
        Container(
          key: const ValueKey('chat-error-banner'),
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color:
                Theme.of(context).colorScheme.errorContainer.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            error,
            style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
          ),
        ),
      if (isRunning)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 6),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(strokeWidth: 1.5),
              ),
              SizedBox(width: 8),
              Text('Thinking…', style: TextStyle(fontSize: 12)),
            ],
          ),
        ),
    ];

    return ListView(
      padding: const EdgeInsets.all(DesignTokens.p16),
      children: children,
    );
  }
}
