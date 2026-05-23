import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../domain/chat_message.dart';
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
      for (var i = 0; i < messages.length; i++) ...[
        ChatMessageBubble(
          message: messages[i],
          toolCalls: i == messages.length - 1 ? activeToolCalls : const [],
        ),
        // Regenerate appears under the LAST assistant message only,
        // and only when no run is in flight. Distinct from Retry
        // (which the error banner owns) — Regenerate works on a
        // successful response that the user wants a fresh take on.
        if (!isRunning &&
            messages[i].role == ChatRole.assistant &&
            i == messages.length - 1)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              key: ValueKey('chat-message-regenerate-${messages[i].id}'),
              onPressed: () => ref
                  .read(chatProvider.notifier)
                  .regenerate(messages[i].id),
              icon: const Icon(Icons.refresh, size: 14),
              label: const Text('Regenerate'),
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: const Size(0, 28),
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                textStyle: const TextStyle(fontSize: 11),
              ),
            ),
          ),
      ],
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
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color:
                Theme.of(context).colorScheme.errorContainer.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  error,
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onErrorContainer,
                  ),
                ),
              ),
              TextButton.icon(
                key: const ValueKey('chat-error-retry'),
                onPressed: () =>
                    ref.read(chatProvider.notifier).retryLastRun(),
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Retry'),
                style: TextButton.styleFrom(
                  foregroundColor:
                      Theme.of(context).colorScheme.onErrorContainer,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: const Size(0, 32),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              ),
              TextButton(
                key: const ValueKey('chat-error-dismiss'),
                onPressed: () =>
                    ref.read(chatProvider.notifier).dismissError(),
                style: TextButton.styleFrom(
                  foregroundColor:
                      Theme.of(context).colorScheme.onErrorContainer,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: const Size(0, 32),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                child: const Text('Dismiss'),
              ),
            ],
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
