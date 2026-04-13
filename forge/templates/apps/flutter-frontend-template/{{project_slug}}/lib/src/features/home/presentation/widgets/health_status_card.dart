import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../theme/design_tokens.dart';
import '../../../../shared/widgets/async_value_widget.dart';
import '../../data/home_repository.dart';

class HealthStatusCard extends ConsumerWidget {
  const HealthStatusCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final healthAsync = ref.watch(healthCheckProvider);
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.p16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.monitor_heart_outlined,
                    color: theme.colorScheme.primary),
                const SizedBox(width: DesignTokens.p8),
                Text('Health Status', style: theme.textTheme.titleMedium),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.refresh, size: DesignTokens.iconMD),
                  onPressed: () => ref.invalidate(healthCheckProvider),
                  tooltip: 'Refresh',
                ),
              ],
            ),
            const Divider(),
            AsyncValueWidget(
              value: healthAsync,
              data: (health) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _StatusIndicator(
                    label: 'Overall',
                    status: health.status,
                  ),
                  if (health.components != null)
                    ...health.components!.entries.map(
                      (entry) => _StatusIndicator(
                        label: entry.key,
                        status: entry.value.status,
                        latencyMs: entry.value.latencyMs,
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusIndicator extends StatelessWidget {
  const _StatusIndicator({
    required this.label,
    required this.status,
    this.latencyMs,
  });

  final String label;
  final String status;
  final double? latencyMs;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (status.toUpperCase()) {
      'UP' => (Colors.green, Icons.check_circle),
      'DOWN' => (Colors.red, Icons.cancel),
      'DEGRADED' => (Colors.orange, Icons.warning),
      _ => (Colors.grey, Icons.help_outline),
    };

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: DesignTokens.p4),
      child: Row(
        children: [
          Icon(icon, size: DesignTokens.iconSM, color: color),
          const SizedBox(width: DesignTokens.p8),
          Text(label),
          if (latencyMs != null) ...[
            const Spacer(),
            Text(
              '${latencyMs!.toStringAsFixed(1)}ms',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ],
      ),
    );
  }
}
