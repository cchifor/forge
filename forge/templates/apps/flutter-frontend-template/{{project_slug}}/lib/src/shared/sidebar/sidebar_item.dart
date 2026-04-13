import 'package:flutter/material.dart';

/// Base sealed class for sidebar items, enabling exhaustive pattern matching.
sealed class SidebarItem {
  const SidebarItem();

  const factory SidebarItem.tile({
    required bool isSelected,
    required VoidCallback onTap,
    required Widget icon,
    String? title,
    Widget? selectedIcon,
    String? tooltip,
    Color? highlightColor,
    Color? hoverColor,
    double itemHeight,
    EdgeInsetsGeometry margin,
  }) = SidebarItemTile;

  const factory SidebarItem.title({
    required String title,
    TextStyle? titleStyle,
    EdgeInsetsGeometry padding,
  }) = SidebarItemTitle;

  const factory SidebarItem.divider({
    EdgeInsetsGeometry padding,
    double? thickness,
    Color? color,
  }) = SidebarItemDivider;
}

/// A tappable navigation item with icon, optional label, and selection state.
class SidebarItemTile extends SidebarItem {
  const SidebarItemTile({
    required this.isSelected,
    required this.onTap,
    required this.icon,
    this.title,
    this.selectedIcon,
    this.tooltip,
    this.highlightColor,
    this.hoverColor,
    this.itemHeight = 40.0,
    this.margin = const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
  });

  final bool isSelected;
  final VoidCallback onTap;
  final Widget icon;
  final String? title;
  final Widget? selectedIcon;
  final String? tooltip;
  final Color? highlightColor;
  final Color? hoverColor;
  final double itemHeight;
  final EdgeInsetsGeometry margin;
}

/// A non-interactive section header label.
class SidebarItemTitle extends SidebarItem {
  const SidebarItemTitle({
    required this.title,
    this.titleStyle,
    this.padding = const EdgeInsets.fromLTRB(16, 16, 16, 4),
  });

  final String title;
  final TextStyle? titleStyle;
  final EdgeInsetsGeometry padding;
}

/// A visual separator line.
class SidebarItemDivider extends SidebarItem {
  const SidebarItemDivider({
    this.padding = const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
    this.thickness,
    this.color,
  });

  final EdgeInsetsGeometry padding;
  final double? thickness;
  final Color? color;
}

/// Shared default styling for [SidebarItemTile] items.
class SidebarTileDefaults {
  const SidebarTileDefaults({
    this.selectedColor,
    this.hoverColor,
    this.borderRadius,
    this.selectedIndicatorWidth = 3.0,
    this.selectedIndicatorHeight = 20.0,
  });

  final Color? selectedColor;
  final Color? hoverColor;
  final BorderRadiusGeometry? borderRadius;
  final double selectedIndicatorWidth;
  final double selectedIndicatorHeight;
}
