import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/design_tokens.dart';
import '../../features/chat/presentation/chat_panel.dart';
import '../../theme/ai_theme_extension.dart';
import '../layout/layout_state.dart';

class ChatButton extends ConsumerWidget {
  const ChatButton({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final layout = ref.watch(layoutStateProvider);
    final isInlineOpen = layout.chatInline;
    final aiColors = Theme.of(context).extension<AiThemeColors>()!;
    final theme = Theme.of(context);

    return Tooltip(
      message: 'Toggle AI Chat (Ctrl+J)',
      child: FilledButton.tonal(
        onPressed: () => _handlePress(context, ref, layout),
        style: FilledButton.styleFrom(
          backgroundColor: isInlineOpen
              ? aiColors.gradientStart.withValues(alpha: 0.15)
              : null,
          padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p16, vertical: DesignTokens.p8),
          visualDensity: VisualDensity.compact,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            ShaderMask(
              shaderCallback: (bounds) =>
                  aiColors.gradient.createShader(bounds),
              child: Icon(
                Icons.auto_awesome,
                size: 18,
                color: isInlineOpen
                    ? theme.colorScheme.onSurface
                    : Colors.white,
              ),
            ),
            const SizedBox(width: DesignTokens.p8),
            Text(
              isInlineOpen ? 'Close AI' : 'Ask AI',
              style: theme.textTheme.labelMedium,
            ),
          ],
        ),
      ),
    );
  }

  void _handlePress(BuildContext context, WidgetRef ref, LayoutState layout) {
    switch (layout.breakpoint) {
      case LayoutBreakpoint.expanded:
        // Inline toggle
        ref.read(layoutStateProvider.notifier).toggleChatPanel();

      case LayoutBreakpoint.medium:
        // Open the Scaffold's endDrawer
        Scaffold.of(context).openEndDrawer();

      case LayoutBreakpoint.compact:
        // Full-screen modal bottom sheet
        showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          useSafeArea: true,
          builder: (_) => DraggableScrollableSheet(
            initialChildSize: 0.9,
            minChildSize: 0.5,
            maxChildSize: 0.95,
            builder: (context, scrollController) =>
                const ChatPanel(isFullScreen: true),
          ),
        );
    }
  }
}
