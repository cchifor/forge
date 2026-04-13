import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../theme/design_tokens.dart';
import '../../features/auth/presentation/auth_controller.dart';
import '../../routing/route_names.dart';
import '../../shared/providers/current_user_provider.dart';

class ProfileMenu extends ConsumerWidget {
  const ProfileMenu({required this.isExpanded, super.key});

  final bool isExpanded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(currentUserProvider);
    final theme = Theme.of(context);

    if (user == null) return const SizedBox.shrink();

    final initials = _initials(user.firstName, user.lastName);

    return MenuAnchor(
      alignmentOffset: const Offset(8, -8),
      menuChildren: [
        // Header
        Padding(
          padding: const EdgeInsets.fromLTRB(DesignTokens.p16, DesignTokens.p12, DesignTokens.p16, DesignTokens.p8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                user.fullName,
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                user.email,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        MenuItemButton(
          leadingIcon: const Icon(Icons.person_outlined, size: DesignTokens.iconMD),
          child: const Text('Account'),
          onPressed: () => context.goNamed(RouteNames.profile),
        ),
        MenuItemButton(
          leadingIcon: const Icon(Icons.settings_outlined, size: DesignTokens.iconMD),
          child: const Text('Preferences'),
          onPressed: () => context.goNamed(RouteNames.settings),
        ),
        const Divider(height: 1),
        MenuItemButton(
          leadingIcon: Icon(
            Icons.logout,
            size: DesignTokens.iconMD,
            color: theme.colorScheme.error,
          ),
          child: Text(
            'Log Out',
            style: TextStyle(color: theme.colorScheme.error),
          ),
          onPressed: () =>
              ref.read(authControllerProvider.notifier).logout(),
        ),
      ],
      builder: (context, controller, _) {
        return InkWell(
          onTap: () {
            if (controller.isOpen) {
              controller.close();
            } else {
              controller.open();
            }
          },
          borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: DesignTokens.p8),
            child: Row(
              children: [
                // Avatar centered in the same column as nav icons
                SizedBox(
                  width: DesignTokens.sidebarIconColumnWidth,
                  child: Center(
                    child: CircleAvatar(
                      radius: DesignTokens.avatarMD,
                      backgroundColor: theme.colorScheme.primaryContainer,
                      child: Text(
                        initials,
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onPrimaryContainer,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(left: DesignTokens.p8),
                    child: Text(
                      user.firstName,
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontWeight: FontWeight.w500,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  String _initials(String first, String last) {
    final f = first.isNotEmpty ? first[0].toUpperCase() : '';
    final l = last.isNotEmpty ? last[0].toUpperCase() : '';
    return '$f$l';
  }
}
