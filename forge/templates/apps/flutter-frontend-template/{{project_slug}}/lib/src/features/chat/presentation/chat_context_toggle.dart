import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../shared/layout/layout_state.dart';
import '../../../theme/ai_theme_extension.dart';
import '../../../theme/layout_theme_extension.dart';

class ChatContextToggle extends ConsumerWidget {
  const ChatContextToggle({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final aiColors = theme.extension<AiThemeColors>()!;
    final layoutExt = theme.extension<LayoutThemeExtension>()!;

    return Container(
      height: layoutExt.headerHeight,
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p12),
      child: Row(
        children: [
          ShaderMask(
            shaderCallback: (bounds) =>
                aiColors.gradient.createShader(bounds),
            child: const Icon(Icons.auto_awesome, size: 18, color: Colors.white),
          ),
          const SizedBox(width: DesignTokens.p8),
          Text(
            'AI Assistant',
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.close, size: 18),
            onPressed: () => ref
                .read(layoutStateProvider.notifier)
                .setChatPanelOpen(false),
            visualDensity: VisualDensity.compact,
            tooltip: 'Close',
          ),
        ],
      ),
    );
  }
}
