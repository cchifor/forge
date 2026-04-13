import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../theme/ai_theme_extension.dart';

class ChatInputBar extends HookConsumerWidget {
  const ChatInputBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useTextEditingController();
    final focusNode = useFocusNode();
    final theme = Theme.of(context);
    final aiColors = theme.extension<AiThemeColors>()!;

    // TODO(chat): Wire isGenerating state for pulsing glow effect.

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
            color: theme.colorScheme.outlineVariant,
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
                decoration: const InputDecoration(
                  hintText: 'Ask anything...',
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(
                    horizontal: DesignTokens.p16,
                    vertical: DesignTokens.p12,
                  ),
                ),
                textInputAction: TextInputAction.newline,
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(right: DesignTokens.p4, bottom: DesignTokens.p4),
              child: IconButton(
                onPressed: () {
                  if (controller.text.trim().isNotEmpty) {
                    controller.clear();
                    // Stub: no send action yet
                  }
                },
                icon: ShaderMask(
                  shaderCallback: (bounds) =>
                      aiColors.gradient.createShader(bounds),
                  child: const Icon(
                    Icons.send_rounded,
                    color: Colors.white,
                  ),
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
