import 'package:flutter/material.dart';

import 'nav_destinations.dart';

/// Compact-tier primary nav region for the tabbar layout. Wraps Flutter's
/// [NavigationBar] (Material 3 bottom tab bar). It renders every entry in the
/// shared [navDestinations] list so the selected-index contract with
/// `scaffold_with_nav.dart` is preserved (bar index == global destination
/// index).
class BottomTabBar extends StatelessWidget {
  const BottomTabBar({
    required this.selectedIndex,
    required this.onDestinationSelected,
    super.key,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  @override
  Widget build(BuildContext context) {
    // --- feature nav items ---
    // The bar maps the full `navDestinations` list 1:1 so feature routes
    // injected at the `// --- feature nav destinations ---` marker in
    // nav_destinations.dart surface here automatically.
    final destinations = [
      for (final dest in navDestinations)
        NavigationDestination(
          icon: Icon(dest.icon),
          selectedIcon: Icon(dest.selectedIcon),
          label: dest.label,
        ),
    ];

    return NavigationBar(
      selectedIndex: selectedIndex,
      onDestinationSelected: onDestinationSelected,
      destinations: destinations,
    );
  }
}
