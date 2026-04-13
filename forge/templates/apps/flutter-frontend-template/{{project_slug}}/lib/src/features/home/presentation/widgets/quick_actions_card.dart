import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../theme/design_tokens.dart';
import '../../../../routing/route_names.dart';

class QuickActionsCard extends StatelessWidget {
  const QuickActionsCard({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.p16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.bolt, color: theme.colorScheme.primary),
                const SizedBox(width: DesignTokens.p8),
                Text('Quick Actions', style: theme.textTheme.titleMedium),
              ],
            ),
            const Divider(),
            Wrap(
              spacing: DesignTokens.p8,
              runSpacing: DesignTokens.p8,
              children: [
                ActionChip(
                  avatar: const Icon(Icons.person_outlined, size: DesignTokens.iconSM),
                  label: const Text('View Profile'),
                  onPressed: () => context.goNamed(RouteNames.profile),
                ),
                ActionChip(
                  avatar: const Icon(Icons.settings_outlined, size: DesignTokens.iconSM),
                  label: const Text('Settings'),
                  onPressed: () => context.goNamed(RouteNames.settings),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
