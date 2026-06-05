import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../theme/design_tokens.dart';
{% if include_chat %}
import '../widgets/chat_button.dart';
{% endif %}
{% if include_auth %}
import 'profile_menu.dart';
{% endif %}
import 'nav_destinations.dart';

/// Horizontal application top bar for the Top-Nav Content Shell.
///
/// On the expanded tier it renders the primary [navDestinations] inline. On the
/// collapsed tiers (medium / compact) it shows a hamburger button that opens
/// [TopNavDrawer] via [onMenuPressed] and hides the inline nav.
class TopNavBar extends ConsumerWidget {
  const TopNavBar({
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.onMenuPressed,
    this.compact = false,
    super.key,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final VoidCallback onMenuPressed;

  /// When true, the inline nav and app title collapse behind a hamburger menu.
  final bool compact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return Material(
      color: theme.colorScheme.surface,
      elevation: 0,
      child: Container(
        height: DesignTokens.workingAreaHeaderHeight,
        decoration: BoxDecoration(
          border: Border(
            bottom: BorderSide(
              color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
            ),
          ),
        ),
        padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p12),
        child: Row(
          children: [
            if (compact)
              IconButton(
                icon: const Icon(Icons.menu),
                onPressed: onMenuPressed,
                tooltip: 'Open navigation menu',
                visualDensity: VisualDensity.compact,
              ),
            // Brand
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p8),
              child: Icon(
                Icons.flutter_dash,
                size: 28,
                color: theme.colorScheme.primary,
              ),
            ),
            if (!compact)
              Text(
                '{{ app_title }}',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  letterSpacing: -0.3,
                ),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
              ),

            // Inline primary nav (expanded tier only)
            if (!compact) ...[
              const SizedBox(width: DesignTokens.p16),
              Expanded(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (final (index, dest) in navDestinations.indexed)
                        if (dest.section == NavSection.primary)
                          _TopNavItem(
                            label: dest.label,
                            icon: dest.icon,
                            selectedIcon: dest.selectedIcon,
                            isSelected: selectedIndex == index,
                            onTap: () => onDestinationSelected(index),
                          ),
                    ],
                  ),
                ),
              ),
            ] else
              const Spacer(),

            // Right cluster
            {% if include_chat %}
            const ChatButton(),
            const SizedBox(width: DesignTokens.p8),
            {% endif %}
            {% if include_auth %}
            const ProfileMenu(isExpanded: false),
            {% endif %}
          ],
        ),
      ),
    );
  }
}

class _TopNavItem extends StatelessWidget {
  const _TopNavItem({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = isSelected
        ? theme.colorScheme.primary
        : theme.colorScheme.onSurfaceVariant;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
        child: Container(
          height: 40,
          padding:
              const EdgeInsets.symmetric(horizontal: DesignTokens.p12),
          decoration: BoxDecoration(
            color: isSelected
                ? theme.colorScheme.primaryContainer.withValues(alpha: 0.3)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(isSelected ? selectedIcon : icon, size: 18, color: color),
              const SizedBox(width: DesignTokens.p8),
              Text(
                label,
                style: theme.textTheme.labelLarge?.copyWith(
                  color: color,
                  fontWeight:
                      isSelected ? FontWeight.w600 : FontWeight.w500,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
