import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/design_tokens.dart';
import '../sidebar/sidebar.dart';
import '../sidebar/sidebar_data.dart';
import '../sidebar/sidebar_item.dart';
import 'layout_state.dart';
import 'nav_destinations.dart';
import 'profile_menu.dart';

class AppSidebar extends ConsumerWidget {
  const AppSidebar({
    required this.selectedIndex,
    required this.onDestinationSelected,
    super.key,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final layout = ref.watch(layoutStateProvider);
    final theme = Theme.of(context);

    return Sidebar(
      isOpen: layout.sidebarExpanded,
      minWidth: DesignTokens.sidebarCollapsedWidth,
      maxWidth: DesignTokens.sidebarExpandedWidth,
      border: Border(
        right: BorderSide(
          color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
        ),
      ),
      builder: (data) {
        return SidebarData(
          header: _SidebarHeader(
            isExpanded: data.isOpen,
            onToggle: () => ref
                .read(layoutStateProvider.notifier)
                .toggleSidebar(),
          ),
          footer: ProfileMenu(isExpanded: data.isOpen),
          tileDefaults: SidebarTileDefaults(
            selectedColor:
                theme.colorScheme.primaryContainer.withValues(alpha: 0.3),
            borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
          ),
          items: _buildPrimaryItems(),
          bottomItems: _buildBottomItems(),
        );
      },
    );
  }

  List<SidebarItem> _buildPrimaryItems() {
    return [
      for (final (index, dest) in navDestinations.indexed)
        if (dest.section == NavSection.primary)
          SidebarItem.tile(
            isSelected: selectedIndex == index,
            onTap: () => onDestinationSelected(index),
            icon: Icon(dest.icon),
            selectedIcon: Icon(dest.selectedIcon),
            title: dest.label,
          ),
    ];
  }

  List<SidebarItem> _buildBottomItems() {
    return [
      const SidebarItem.divider(),
      for (final (index, dest) in navDestinations.indexed)
        if (dest.section == NavSection.bottom)
          SidebarItem.tile(
            isSelected: selectedIndex == index,
            onTap: () => onDestinationSelected(index),
            icon: Icon(dest.icon),
            selectedIcon: Icon(dest.selectedIcon),
            title: dest.label,
          ),
    ];
  }
}

class _SidebarHeader extends StatelessWidget {
  const _SidebarHeader({required this.isExpanded, required this.onToggle});

  final bool isExpanded;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SizedBox(
      height: DesignTokens.workingAreaHeaderHeight,
      child: Row(
        children: [
          // Icon centered in the same column as nav item icons
          SizedBox(
            width: DesignTokens.sidebarIconColumnWidth,
            child: Center(
              child: IconButton(
                icon: Icon(
                  Icons.flutter_dash,
                  size: 28,
                  color: theme.colorScheme.primary,
                ),
                onPressed: onToggle,
                tooltip: isExpanded ? 'Collapse sidebar' : 'Expand sidebar',
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
              ),
            ),
          ),
          // App name: always in the Row, Expanded absorbs 0px when collapsed.
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(left: DesignTokens.p8),
              child: Text(
                'Platform',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  letterSpacing: -0.3,
                ),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
