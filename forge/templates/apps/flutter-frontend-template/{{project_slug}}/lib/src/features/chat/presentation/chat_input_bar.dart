import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../theme/ai_theme_extension.dart';
import 'chat_providers.dart';

class ChatInputBar extends HookConsumerWidget {
  const ChatInputBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useTextEditingController();
    final focusNode = useFocusNode();
    final theme = Theme.of(context);
    final aiColors = theme.extension<AiThemeColors>()!;
    final isGenerating = ref.watch(chatIsRunningProvider);

    void send() {
      final text = controller.text.trim();
      if (text.isEmpty || isGenerating) return;
      ref.read(chatProvider.notifier).sendMessage(text);
      controller.clear();
    }

    return Container(
      padding: const EdgeInsets.all(DesignTokens.p12),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
          ),
        ),
      ),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(DesignTokens.radiusLarge),
          border: Border.all(
            color: isGenerating
                ? aiColors.gradientStart.withValues(alpha: 0.5)
                : theme.colorScheme.outlineVariant,
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                focusNode: focusNode,
                maxLines: 4,
                minLines: 1,
                enabled: !isGenerating,
                onSubmitted: (_) => send(),
                decoration: const InputDecoration(
                  hintText: 'Ask anything...',
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(
                    horizontal: DesignTokens.p16,
                    vertical: DesignTokens.p12,
                  ),
                ),
                textInputAction: TextInputAction.send,
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(
                right: DesignTokens.p4,
                bottom: DesignTokens.p4,
              ),
              child: IconButton(
                key: const ValueKey('chat-send-button'),
                onPressed: isGenerating ? null : send,
                icon: ShaderMask(
                  shaderCallback: (bounds) => aiColors.gradient.createShader(bounds),
                  child: const Icon(Icons.send_rounded, color: Colors.white),
                ),
                tooltip: 'Send',
              ),
            ),
          ],
        ),
      ),
    );
  }
}
