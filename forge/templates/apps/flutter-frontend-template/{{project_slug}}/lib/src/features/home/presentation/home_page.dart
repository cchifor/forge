import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../shared/providers/current_user_provider.dart';
import 'widgets/health_status_card.dart';
import 'widgets/info_card.dart';
import 'widgets/quick_actions_card.dart';

class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);
    final theme = Theme.of(context);

    return Scaffold(
      body: ListView(
        padding: const EdgeInsets.all(DesignTokens.p16),
        children: [
          if (user != null) ...[
            Text(
              'Welcome back, ${user.firstName}!',
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: DesignTokens.p4),
            Text(
              'Here\'s an overview of your workspace.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: DesignTokens.p24),
          ],
          const QuickActionsCard(),
          const SizedBox(height: DesignTokens.p16),
          const InfoCard(),
          const SizedBox(height: DesignTokens.p16),
          const HealthStatusCard(),
        ],
      ),
    );
  }
}
