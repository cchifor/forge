import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../theme/design_tokens.dart';
import '../../../../shared/widgets/async_value_widget.dart';
import '../../../../theme/layout_theme_extension.dart';
import '../../data/home_repository.dart';

class InfoCard extends ConsumerWidget {
  const InfoCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final infoAsync = ref.watch(serviceInfoProvider);
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.p16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.info_outline, color: theme.colorScheme.primary),
                const SizedBox(width: DesignTokens.p8),
                Text('Service Info', style: theme.textTheme.titleMedium),
              ],
            ),
            const Divider(),
            AsyncValueWidget(
              value: infoAsync,
              data: (info) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _InfoRow(label: 'Title', value: info.title),
                  _InfoRow(label: 'Version', value: info.version),
                  _InfoRow(label: 'Description', value: info.description),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final layoutExt = Theme.of(context).extension<LayoutThemeExtension>()!;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: DesignTokens.p4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: layoutExt.labelWidth,
            child: Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
