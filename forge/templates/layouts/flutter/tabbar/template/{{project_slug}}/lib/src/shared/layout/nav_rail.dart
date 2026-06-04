import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/design_tokens.dart';
import 'layout_state.dart';
import 'nav_destinations.dart';
{% if include_auth %}import 'profile_menu.dart';
{% endif %}

/// Vertical primary-nav region for the tabbar layout's medium and expanded
/// tiers. Wraps Flutter's [NavigationRail]; collapses to an icon-only rail on
/// medium and promotes to an extended (icon + label) rail on expanded.
///
/// The rail maps directly onto the shared [navDestinations] list so the
/// selected-index contract with `scaffold_with_nav.dart` is preserved: the
/// rail's index == the global destination index.
class NavRail extends ConsumerWidget {
  const NavRail({
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.extended,
    super.key,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  /// When true the rail shows labels beside icons (expanded tier); when false
  /// it is an icon-only column (medium tier).
  final bool extended;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    // --- feature nav items ---
    // The rail renders every entry in `navDestinations` so feature routes
    // injected at the `// --- feature nav destinations ---` marker in
    // nav_destinations.dart appear automatically. NavigationRail requires its
    // own destinations to be index-aligned with the global list, so we map the
    // full list 1:1 and keep the selected index in the same coordinate space.
    final destinations = [
      for (final dest in navDestinations)
        NavigationRailDestination(
          icon: Icon(dest.icon),
          selectedIcon: Icon(dest.selectedIcon),
          label: Text(dest.label),
        ),
    ];

    return Container(
      decoration: BoxDecoration(
        border: Border(
          right: BorderSide(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
          ),
        ),
      ),
      child: Column(
        children: [
          Expanded(
            child: NavigationRail(
              extended: extended,
              minWidth: DesignTokens.navRailWidth,
              minExtendedWidth: DesignTokens.navRailExtendedWidth,
              selectedIndex: selectedIndex,
              onDestinationSelected: onDestinationSelected,
              labelType: extended
                  ? NavigationRailLabelType.none
                  : NavigationRailLabelType.all,
              leading: const _RailLeading(),
              destinations: destinations,
            ),
          ),
          {% if include_auth %}const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: DesignTokens.sidebarBodyPadding,
              vertical: DesignTokens.p8,
            ),
            child: ProfileMenu(isExpanded: extended),
          ),
          {% endif %}],
      ),
    );
  }
}

class _RailLeading extends StatelessWidget {
  const _RailLeading();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: DesignTokens.p16),
      child: Icon(
        Icons.flutter_dash,
        size: 28,
        color: theme.colorScheme.primary,
      ),
    );
  }
}
