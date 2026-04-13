import 'package:flutter/material.dart';

import 'sidebar_item.dart';

/// Data returned by the [Sidebar] builder function.
class SidebarData {
  const SidebarData({
    this.header,
    this.footer,
    this.items = const [],
    this.bottomItems = const [],
    this.tileDefaults,
  });

  /// Widget displayed at the top of the sidebar (e.g., logo, branding).
  final Widget? header;

  /// Widget displayed at the bottom of the sidebar (e.g., profile menu).
  final Widget? footer;

  /// Primary items in the scrollable area.
  final List<SidebarItem> items;

  /// Items pinned above the footer (e.g., Settings, Profile).
  final List<SidebarItem> bottomItems;

  /// Shared default styling applied to all [SidebarItemTile] items.
  final SidebarTileDefaults? tileDefaults;
}

/// Data passed to the [Sidebar] builder function so items can adapt
/// to the current open/collapsed state.
class SidebarBuilderData {
  const SidebarBuilderData({
    required this.isOpen,
    required this.currentWidth,
    required this.minWidth,
    required this.maxWidth,
  });

  final bool isOpen;
  final double currentWidth;
  final double minWidth;
  final double maxWidth;
}
