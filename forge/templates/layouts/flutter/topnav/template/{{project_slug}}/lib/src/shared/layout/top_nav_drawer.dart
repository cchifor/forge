import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
{% if include_auth %}import 'profile_menu.dart';
{% endif %}import 'nav_destinations.dart';

/// Hamburger navigation drawer for the Top-Nav Content Shell.
///
/// Surfaced as the [Scaffold.drawer] on the medium and compact tiers, it lists
/// every entry in [navDestinations] (primary section, then a divider, then the
/// bottom section) and closes itself on selection.
class TopNavDrawer extends StatelessWidget {
  const TopNavDrawer({
    required this.selectedIndex,
    required this.onDestinationSelected,
    super.key,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Drawer(
      child: SafeArea(
        child: Column(
          children: [
            // Header
            SizedBox(
              height: DesignTokens.workingAreaHeaderHeight,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: DesignTokens.p16,
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.flutter_dash,
                      size: 28,
                      color: theme.colorScheme.primary,
                    ),
                    const SizedBox(width: DesignTokens.p8),
                    Expanded(
                      child: Text(
                        '{{ app_title }}',
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                          letterSpacing: -0.3,
                        ),
                        overflow: TextOverflow.ellipsis,
                        maxLines: 1,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const Divider(height: 1),

            // Nav items
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(
                  vertical: DesignTokens.p8,
                ),
                children: [
                  for (final (index, dest) in navDestinations.indexed)
                    if (dest.section == NavSection.primary)
                      _DrawerTile(
                        label: dest.label,
                        icon: dest.icon,
                        selectedIcon: dest.selectedIcon,
                        isSelected: selectedIndex == index,
                        onTap: () => _select(context, index),
                      ),
                  const Divider(),
                  for (final (index, dest) in navDestinations.indexed)
                    if (dest.section == NavSection.bottom)
                      _DrawerTile(
                        label: dest.label,
                        icon: dest.icon,
                        selectedIcon: dest.selectedIcon,
                        isSelected: selectedIndex == index,
                        onTap: () => _select(context, index),
                      ),
                ],
              ),
            ),
            {% if include_auth %}const Divider(height: 1),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: DesignTokens.p8),
              child: ProfileMenu(isExpanded: true),
            ),
            {% endif %}
          ],
        ),
      ),
    );
  }

  void _select(BuildContext context, int index) {
    onDestinationSelected(index);
    Navigator.of(context).maybePop();
  }
}

class _DrawerTile extends StatelessWidget {
  const _DrawerTile({
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

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p8),
      child: ListTile(
        selected: isSelected,
        selectedColor: theme.colorScheme.primary,
        selectedTileColor:
            theme.colorScheme.primaryContainer.withValues(alpha: 0.3),
        leading: Icon(isSelected ? selectedIcon : icon),
        title: Text(label),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
        ),
        onTap: onTap,
      ),
    );
  }
}
