import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../theme/theme_provider.dart';
import '../../domain/settings_model.dart';

class TextSizeSelector extends ConsumerWidget {
  const TextSizeSelector({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final textSize = ref.watch(textSizeProvider);

    return SegmentedButton<TextSize>(
      segments: const [
        ButtonSegment(
          value: TextSize.small,
          icon: Icon(Icons.text_decrease),
          label: Text('Small'),
        ),
        ButtonSegment(
          value: TextSize.medium,
          icon: Icon(Icons.text_fields),
          label: Text('Medium'),
        ),
        ButtonSegment(
          value: TextSize.large,
          icon: Icon(Icons.text_increase),
          label: Text('Large'),
        ),
      ],
      selected: {textSize},
      onSelectionChanged: (selected) {
        ref.read(textSizeProvider.notifier).setTextSize(
              selected.first,
            );
      },
    );
  }
}
