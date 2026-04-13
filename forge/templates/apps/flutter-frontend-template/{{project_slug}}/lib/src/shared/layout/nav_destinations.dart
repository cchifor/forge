import 'package:flutter/material.dart';

enum NavSection { primary, bottom }

typedef NavDestination = ({
  IconData icon,
  IconData selectedIcon,
  String label,
  NavSection section,
});

const List<NavDestination> navDestinations = [
  (
    icon: Icons.home_outlined,
    selectedIcon: Icons.home,
    label: 'Home',
    section: NavSection.primary,
  ),
  // --- feature nav destinations ---
  (
    icon: Icons.person_outlined,
    selectedIcon: Icons.person,
    label: 'Profile',
    section: NavSection.bottom,
  ),
  (
    icon: Icons.settings_outlined,
    selectedIcon: Icons.settings,
    label: 'Settings',
    section: NavSection.bottom,
  ),
];
