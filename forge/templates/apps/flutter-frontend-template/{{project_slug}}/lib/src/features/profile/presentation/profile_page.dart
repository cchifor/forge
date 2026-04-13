import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../theme/design_tokens.dart';
import '../../../features/auth/presentation/auth_controller.dart';
import '../../../shared/providers/current_user_provider.dart';

class ProfilePage extends ConsumerWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);
    final theme = Theme.of(context);

    if (user == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      body: ListView(
        padding: const EdgeInsets.all(DesignTokens.p16),
        children: [
          Center(
            child: CircleAvatar(
              radius: DesignTokens.avatarLG,
              backgroundColor: theme.colorScheme.primaryContainer,
              child: Text(
                _initials(user.firstName, user.lastName),
                style: theme.textTheme.headlineMedium?.copyWith(
                  color: theme.colorScheme.onPrimaryContainer,
                ),
              ),
            ),
          ),
          const SizedBox(height: DesignTokens.p16),
          Center(
            child: Text(
              user.fullName,
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          Center(
            child: Text(
              '@${user.username}',
              style: theme.textTheme.bodyLarge?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          const SizedBox(height: DesignTokens.p24),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.email_outlined),
                  title: const Text('Email'),
                  subtitle: Text(user.email),
                ),
                ListTile(
                  leading: const Icon(Icons.badge_outlined),
                  title: const Text('User ID'),
                  subtitle: Text(user.id),
                ),
                ListTile(
                  leading: const Icon(Icons.business_outlined),
                  title: const Text('Customer ID'),
                  subtitle: Text(user.customerId),
                ),
                if (user.orgId != null)
                  ListTile(
                    leading: const Icon(Icons.corporate_fare_outlined),
                    title: const Text('Organization'),
                    subtitle: Text(user.orgId!),
                  ),
              ],
            ),
          ),
          const SizedBox(height: DesignTokens.p16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(DesignTokens.p16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Roles', style: theme.textTheme.titleMedium),
                  const SizedBox(height: DesignTokens.p8),
                  Wrap(
                    spacing: DesignTokens.p8,
                    runSpacing: DesignTokens.p8,
                    children: user.roles
                        .map(
                          (role) => Chip(
                            avatar: const Icon(Icons.shield_outlined, size: DesignTokens.iconSM),
                            label: Text(role),
                          ),
                        )
                        .toList(),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: DesignTokens.p24),
          Center(
            child: OutlinedButton.icon(
              onPressed: () =>
                  ref.read(authControllerProvider.notifier).logout(),
              icon: const Icon(Icons.logout),
              label: const Text('Sign Out'),
              style: OutlinedButton.styleFrom(
                foregroundColor: theme.colorScheme.error,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _initials(String firstName, String lastName) {
    final first = firstName.isNotEmpty ? firstName[0].toUpperCase() : '';
    final last = lastName.isNotEmpty ? lastName[0].toUpperCase() : '';
    return '$first$last';
  }
}
