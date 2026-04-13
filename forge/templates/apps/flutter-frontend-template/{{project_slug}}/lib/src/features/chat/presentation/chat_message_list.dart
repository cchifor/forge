import 'package:flutter/material.dart';

import '../../../theme/design_tokens.dart';
import '../../../theme/ai_theme_extension.dart';
import '../domain/chat_message.dart';

class ChatMessageList extends StatelessWidget {
  const ChatMessageList({super.key});

  static final _stubMessages = [
    ChatMessage(
      id: '1',
      content:
          'Hello! I\'m your AI assistant. I can help you with tasks, answer questions about your workspace, or assist with data analysis. How can I help you today?',
      role: ChatRole.assistant,
      timestamp: DateTime.now(),
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final messages = _stubMessages;

    return ListView.builder(
      padding: const EdgeInsets.all(DesignTokens.p16),
      itemCount: messages.length,
      itemBuilder: (context, index) {
        final msg = messages[index];
        return _ChatBubble(message: msg);
      },
    );
  }
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final aiColors = theme.extension<AiThemeColors>()!;
    final isAssistant = message.role == ChatRole.assistant;

    return Padding(
      padding: const EdgeInsets.only(bottom: DesignTokens.p16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Avatar
          CircleAvatar(
            radius: DesignTokens.avatarSM,
            backgroundColor: isAssistant
                ? aiColors.gradientStart.withValues(alpha: 0.15)
                : theme.colorScheme.primaryContainer,
            child: isAssistant
                ? ShaderMask(
                    shaderCallback: (bounds) =>
                        aiColors.gradient.createShader(bounds),
                    child: const Icon(
                      Icons.auto_awesome,
                      size: DesignTokens.iconXS,
                      color: Colors.white,
                    ),
                  )
                : Icon(
                    Icons.person,
                    size: DesignTokens.iconXS,
                    color: theme.colorScheme.onPrimaryContainer,
                  ),
          ),
          const SizedBox(width: DesignTokens.p12),

          // Message content
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isAssistant ? 'AI Assistant' : 'You',
                  style: theme.textTheme.labelSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: isAssistant
                        ? aiColors.gradientStart
                        : theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: DesignTokens.p4),
                Text(
                  message.content,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    height: 1.6,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
