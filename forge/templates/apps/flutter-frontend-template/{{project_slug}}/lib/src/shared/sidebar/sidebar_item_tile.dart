import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
import 'sidebar_item.dart';

/// Renders a [SidebarItemTile] with selection indicator, icon, and label.
///
/// Uses [DesignTokens.sidebarIconColumnWidth] to ensure all icons align on
/// the same vertical axis in both collapsed and expanded modes.
class SidebarItemTileWidget extends StatelessWidget {
  const SidebarItemTileWidget({
    required this.item,
    required this.isOpen,
    this.defaults,
    super.key,
  });

  final SidebarItemTile item;
  final bool isOpen;
  final SidebarTileDefaults? defaults;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final selectedColor =
        item.highlightColor ??
        defaults?.selectedColor ??
        theme.colorScheme.primaryContainer.withValues(alpha: 0.3);
    final hovColor =
        item.hoverColor ?? defaults?.hoverColor ?? theme.hoverColor;
    final radius = defaults?.borderRadius ?? BorderRadius.circular(12);
    final indicatorWidth = defaults?.selectedIndicatorWidth ?? 3.0;
    final indicatorHeight = defaults?.selectedIndicatorHeight ?? 20.0;

    final effectiveIcon =
        item.isSelected ? (item.selectedIcon ?? item.icon) : item.icon;
    final tooltipText = item.tooltip ?? item.title;

    final iconColor = item.isSelected
        ? theme.colorScheme.primary
        : theme.colorScheme.onSurfaceVariant;

    Widget child = Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: item.onTap,
        hoverColor: hovColor,
        borderRadius: radius as BorderRadius,
        child: Container(
          height: item.itemHeight,
          decoration: BoxDecoration(
            color: item.isSelected ? selectedColor : Colors.transparent,
            borderRadius: radius,
          ),
          child: Row(
            children: [
              // Fixed-width icon column: all icons center within this
              // regardless of collapsed/expanded state.
              SizedBox(
                width: DesignTokens.sidebarIconColumnWidth,
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    // Selection indicator at left edge
                    if (item.isSelected)
                      Positioned(
                        left: 0,
                        child: Container(
                          width: indicatorWidth,
                          height: indicatorHeight,
                          decoration: BoxDecoration(
                            color: theme.colorScheme.primary,
                            borderRadius: BorderRadius.circular(
                              indicatorWidth / 2,
                            ),
                          ),
                        ),
                      ),
                    // Centered icon
                    IconTheme(
                      data: IconThemeData(color: iconColor, size: 24),
                      child: effectiveIcon,
                    ),
                  ],
                ),
              ),
              // Label: always in the Row. Expanded absorbs remaining
              // space (0px when collapsed, full width when expanded).
              // No overflow at any intermediate animation frame.
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(
                    left: DesignTokens.p8,
                    right: DesignTokens.p8,
                  ),
                  child: Text(
                    item.title ?? '',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: iconColor,
                      fontWeight: item.isSelected
                          ? FontWeight.w600
                          : FontWeight.normal,
                    ),
                    overflow: TextOverflow.ellipsis,
                    maxLines: 1,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );

    if (!isOpen && tooltipText != null) {
      child = Tooltip(message: tooltipText, child: child);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: child,
    );
  }
}
