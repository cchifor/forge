import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../presentation/chat_providers.dart';
import 'canvas_registry.dart';

class CanvasPane extends ConsumerWidget {
  const CanvasPane({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activity = ref.watch(chatProvider.select((s) => s.canvasActivity));
    if (activity == null) return const SizedBox.shrink();
    final entry = CanvasRegistry.resolve(activity.activityType);
    final theme = Theme.of(context);
    return Column(
      key: const ValueKey('canvas-pane'),
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
              Expanded(child: Text(entry.label, style: theme.textTheme.titleSmall)),
              IconButton(
                tooltip: 'Close',
                icon: const Icon(Icons.close, size: 18),
                onPressed: () => ref.read(chatProvider.notifier).clearCanvas(),
              ),
            ],
          ),
        ),
        Expanded(child: entry.builder(context, activity, null)),
      ],
    );
  }
}
