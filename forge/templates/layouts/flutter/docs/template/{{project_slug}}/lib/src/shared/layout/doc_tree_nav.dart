import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
{% if include_auth %}import 'profile_menu.dart';
{% endif %}import 'nav_destinations.dart';

/// Left documentation navigation tree for the Documentation 3-Column shell.
///
/// Renders [navDestinations] as a grouped reading tree: a "Guides" group holds
/// every [NavSection.primary] entry (the generated feature pages are injected
/// into `nav_destinations.dart` by the base post_generate) and a "Reference"
/// group holds the [NavSection.bottom] entries. Groups are collapsible and the
/// active group seeds itself open.
///
/// Two variants share the same tree:
///   * [DocTreeNav] (inline): a persistent ~260px left column on the expanded
///     and medium tiers; [collapsed] shrinks it to an icon rail.
///   * [DocTreeNav.drawer] : a [Drawer] surfaced as the [Scaffold.drawer] on
///     the compact tier (opened from the docs toolbar hamburger).
class DocTreeNav extends StatefulWidget {
  const DocTreeNav({
    required this.selectedIndex,
    required this.onDestinationSelected,
    this.collapsed = false,
    super.key,
  }) : isDrawer = false;

  const DocTreeNav.drawer({
    required this.selectedIndex,
    required this.onDestinationSelected,
    super.key,
  })  : collapsed = false,
        isDrawer = true;

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  /// Inline-only: shrink the column to an icon rail.
  final bool collapsed;

  /// When true, render as a [Drawer] for the compact tier.
  final bool isDrawer;

  @override
  State<DocTreeNav> createState() => _DocTreeNavState();
}

class _DocTreeNavState extends State<DocTreeNav> {
  static const _guidesTitle = 'Guides';
  static const _referenceTitle = 'Reference';

  late final Map<String, bool> _expanded = {
    _guidesTitle: true,
    _referenceTitle: true,
  };

  bool get _collapsed => widget.isDrawer ? false : widget.collapsed;

  void _toggleGroup(String title) {
    setState(() => _expanded[title] = !(_expanded[title] ?? false));
  }

  void _select(int index) {
    widget.onDestinationSelected(index);
    if (widget.isDrawer) Navigator.of(context).maybePop();
  }

  List<({int index, NavDestination dest})> _section(NavSection section) {
    return [
      for (final (index, dest) in navDestinations.indexed)
        if (dest.section == section) (index: index, dest: dest),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final nav = ListView(
      padding: const EdgeInsets.symmetric(
        vertical: DesignTokens.p8,
        horizontal: DesignTokens.p8,
      ),
      children: [
        _DocGroup(
          title: _guidesTitle,
          icon: Icons.menu_book_outlined,
          collapsed: _collapsed,
          expanded: _expanded[_guidesTitle] ?? true,
          onToggle: () => _toggleGroup(_guidesTitle),
          children: [
            // --- feature nav items ---
            for (final entry in _section(NavSection.primary))
              _DocLeaf(
                label: entry.dest.label,
                icon: entry.dest.icon,
                selectedIcon: entry.dest.selectedIcon,
                isSelected: widget.selectedIndex == entry.index,
                collapsed: _collapsed,
                onTap: () => _select(entry.index),
              ),
          ],
        ),
        _DocGroup(
          title: _referenceTitle,
          icon: Icons.bookmark_outline,
          collapsed: _collapsed,
          expanded: _expanded[_referenceTitle] ?? true,
          onToggle: () => _toggleGroup(_referenceTitle),
          children: [
            for (final entry in _section(NavSection.bottom))
              _DocLeaf(
                label: entry.dest.label,
                icon: entry.dest.icon,
                selectedIcon: entry.dest.selectedIcon,
                isSelected: widget.selectedIndex == entry.index,
                collapsed: _collapsed,
                onTap: () => _select(entry.index),
              ),
          ],
        ),
      ],
    );

    final header = SizedBox(
      height: DesignTokens.workingAreaHeaderHeight,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p12),
        child: Row(
          children: [
            SizedBox(
              width: DesignTokens.sidebarIconColumnWidth,
              child: Center(
                child: Icon(
                  Icons.flutter_dash,
                  size: 28,
                  color: theme.colorScheme.primary,
                ),
              ),
            ),
            if (!_collapsed)
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
    );

    final body = Column(
      children: [
        header,
        const Divider(height: 1),
        Expanded(child: nav),
        {% if include_auth %}const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p8),
          child: ProfileMenu(isExpanded: !_collapsed),
        ),
        {% endif %}
      ],
    );

    if (widget.isDrawer) {
      return Drawer(child: SafeArea(child: body));
    }

    return AnimatedContainer(
      duration: const Duration(milliseconds: DesignTokens.durationNormal),
      curve: Curves.easeInOut,
      width: _collapsed
          ? DesignTokens.sidebarCollapsedWidth
          : DesignTokens.sidebarExpandedWidth,
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        border: Border(
          right: BorderSide(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
          ),
        ),
      ),
      child: body,
    );
  }
}

class _DocGroup extends StatelessWidget {
  const _DocGroup({
    required this.title,
    required this.icon,
    required this.collapsed,
    required this.expanded,
    required this.onToggle,
    required this.children,
  });

  final String title;
  final IconData icon;
  final bool collapsed;
  final bool expanded;
  final VoidCallback onToggle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (collapsed) {
      // Icon rail: show only the leaf icons, no group chrome.
      return Column(children: children);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        InkWell(
          onTap: onToggle,
          borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: DesignTokens.p12,
              vertical: DesignTokens.p8,
            ),
            child: Row(
              children: [
                Icon(
                  icon,
                  size: DesignTokens.iconMD,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                const SizedBox(width: DesignTokens.p12),
                Expanded(
                  child: Text(
                    title,
                    style: theme.textTheme.labelLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                AnimatedRotation(
                  turns: expanded ? 0.25 : 0,
                  duration:
                      const Duration(milliseconds: DesignTokens.durationFast),
                  child: Icon(
                    Icons.chevron_right,
                    size: DesignTokens.iconMD,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (expanded)
          Padding(
            padding: const EdgeInsets.only(left: DesignTokens.p12),
            child: Column(children: children),
          ),
      ],
    );
  }
}

class _DocLeaf extends StatelessWidget {
  const _DocLeaf({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.isSelected,
    required this.collapsed,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final bool isSelected;
  final bool collapsed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = isSelected
        ? theme.colorScheme.primary
        : theme.colorScheme.onSurfaceVariant;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
        child: Tooltip(
          message: collapsed ? label : '',
          child: Container(
            height: 36,
            padding: EdgeInsets.symmetric(
              horizontal: collapsed ? 0 : DesignTokens.p12,
            ),
            decoration: BoxDecoration(
              color: isSelected
                  ? theme.colorScheme.primaryContainer.withValues(alpha: 0.3)
                  : Colors.transparent,
              borderRadius: BorderRadius.circular(DesignTokens.radiusMedium),
            ),
            child: collapsed
                ? Center(
                    child: Icon(
                      isSelected ? selectedIcon : icon,
                      size: DesignTokens.iconMD,
                      color: color,
                    ),
                  )
                : Row(
                    children: [
                      Icon(
                        isSelected ? selectedIcon : icon,
                        size: DesignTokens.iconSM,
                        color: color,
                      ),
                      const SizedBox(width: DesignTokens.p12),
                      Expanded(
                        child: Text(
                          label,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: color,
                            fontWeight:
                                isSelected ? FontWeight.w600 : FontWeight.w500,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}
