import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../theme/design_tokens.dart';
{% if include_chat %}import '../../theme/layout_theme_extension.dart';
{% endif %}import 'breadcrumb_bar.dart';
import 'doc_tree_nav.dart';
import 'layout_state.dart';
import 'nav_destinations.dart';
import 'toc_panel.dart';
{% if include_chat %}import '../widgets/chat_button.dart';
import '../../features/chat/presentation/chat_panel.dart';
import 'vertical_split_handle.dart';
{% endif %}
// --- feature nav items ---
// Nav destinations are injected into nav_destinations.dart by the base
// post_generate; DocTreeNav renders them directly as the left reading tree.

/// Documentation 3-Column shell.
///
/// A reading-centric layout: a left [DocTreeNav] tree, a centered max-width
/// article column with its own breadcrumb header, and a right [TocPanel]
/// table-of-contents.
///
///   * expanded (>= 840px): all three columns; the left tree is collapsible
///     via a header toggle, the TocPanel is the persistent right column.
///   * medium (600-840px): tree + content; the TocPanel collapses into a
///     header-triggered modal so the article keeps its readable width.
///   * compact (< 600px): content only; the tree becomes a [Scaffold.drawer]
///     and the TocPanel is hidden. A bottom [NavigationBar] mirrors the tree.
///
/// The TocPanel owns the right column, so chat is surfaced as an overlay (never
/// inline alongside the TOC): an inline resizable pane at expanded, an
/// endDrawer at medium, and a modal bottom sheet at compact — the medium and
/// compact variants ride the shared [ChatButton] in the article header. When
/// chat is disabled, every chat reference is Jinja-gated away and the shell
/// degrades to a clean docs reader.
class AppLayoutShell extends HookConsumerWidget {
  const AppLayoutShell({
    required this.navigationShell,
    required this.selectedIndex,
    required this.onDestinationSelected,
    super.key,
  });

  final Widget navigationShell;
  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final layout = ref.watch(layoutStateProvider);

    return LayoutBuilder(
      builder: (context, constraints) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          ref
              .read(layoutStateProvider.notifier)
              .setScreenWidth(constraints.maxWidth);
        });

        return switch (layout.breakpoint) {
          LayoutBreakpoint.expanded => _ExpandedLayout(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
            body: navigationShell,
            layout: layout,
          ),
          LayoutBreakpoint.medium => _MediumLayout(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
            body: navigationShell,
          ),
          LayoutBreakpoint.compact => _CompactLayout(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
            body: navigationShell,
          ),
        };
      },
    );
  }
}

/// Article header: a tree-collapse toggle (expanded tier only), breadcrumbs,
/// and the shared [ChatButton]. Defined locally instead of reusing
/// `WorkingAreaHeader` because the base only strips that widget's chat button
/// for the `sidebar` layout; here every chat reference is Jinja-gated directly.
class _ArticleHeader extends StatelessWidget {
  const _ArticleHeader({this.onToggleTree, this.onShowToc});

  /// Expanded tier: toggle the left [DocTreeNav] between full and icon rail.
  final VoidCallback? onToggleTree;

  /// Medium tier: open the [TocPanel] as a modal.
  final VoidCallback? onShowToc;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: DesignTokens.workingAreaHeaderHeight,
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p16),
      child: Row(
        children: [
          if (onToggleTree != null)
            Padding(
              padding: const EdgeInsets.only(right: DesignTokens.p8),
              child: IconButton(
                icon: const Icon(Icons.menu_open),
                onPressed: onToggleTree,
                tooltip: 'Toggle navigation',
                visualDensity: VisualDensity.compact,
              ),
            ),
          const BreadcrumbBar(),
          const Spacer(),
          if (onShowToc != null)
            Padding(
              padding: const EdgeInsets.only(right: DesignTokens.p8),
              child: IconButton(
                icon: const Icon(Icons.toc),
                onPressed: onShowToc,
                tooltip: 'On this page',
                visualDensity: VisualDensity.compact,
              ),
            ),
{% if include_chat %}          const ChatButton(),
{% endif %}        ],
      ),
    );
  }
}

/// Centered, readable-width article column shared by every tier.
class _ArticleArea extends StatelessWidget {
  const _ArticleArea({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 768),
        child: child,
      ),
    );
  }
}

// ============================================================
// EXPANDED (>= 840px): DocTreeNav | article | TocPanel (3-col)
// ============================================================
class _ExpandedLayout extends ConsumerStatefulWidget {
  const _ExpandedLayout({
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.body,
    required this.layout,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final Widget body;
  final LayoutState layout;

  @override
  ConsumerState<_ExpandedLayout> createState() => _ExpandedLayoutState();
}

class _ExpandedLayoutState extends ConsumerState<_ExpandedLayout> {
  bool _treeCollapsed = false;
{% if include_chat %}  bool _isDragging = false;
{% endif %}
  void _toggleTree() => setState(() => _treeCollapsed = !_treeCollapsed);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
{% if include_chat %}    final layout = widget.layout;
    final layoutExt = theme.extension<LayoutThemeExtension>()!;
{% endif %}
    return LayoutBuilder(
      builder: (context, constraints) {
{% if include_chat %}        final availableWidth = constraints.maxWidth;
        final maxChatWidth = availableWidth - layoutExt.minMainAreaWidth;
        final chatWidth = layout.chatInline
            ? (layout.chatWidthRatio * availableWidth).clamp(
                layoutExt.minChatWidth,
                maxChatWidth.clamp(layoutExt.minChatWidth, double.infinity),
              )
            : 0.0;

{% endif %}        return Material(
          color: theme.scaffoldBackgroundColor,
          child: {% if include_chat %}MouseRegion(
            cursor: _isDragging
                ? SystemMouseCursors.resizeColumn
                : MouseCursor.defer,
            child: {% endif %}Row(
              children: [
                // Left documentation tree (collapsible).
                DocTreeNav(
                  selectedIndex: widget.selectedIndex,
                  onDestinationSelected: widget.onDestinationSelected,
                  collapsed: _treeCollapsed,
                ),

                // Center article column.
                Expanded(
                  child: {% if include_chat %}IgnorePointer(
                    ignoring: _isDragging,
                    child: {% endif %}Column(
                      children: [
                        _ArticleHeader(onToggleTree: _toggleTree),
                        Expanded(
                          child: _ArticleArea(child: widget.body),
                        ),
                      ],
                    ),
{% if include_chat %}                  ),
{% endif %}                ),

                // Right table-of-contents column.
                const TocPanel(),

{% if include_chat %}                // Splitter + inline chat overlay (explicit width).
                if (layout.chatInline) ...[
                  VerticalSplitHandle(
                    onDragStart: () =>
                        setState(() => _isDragging = true),
                    onDragUpdate: (globalX) {
                      final newRatio =
                          (constraints.maxWidth - globalX - layoutExt.splitterWidth / 2) / availableWidth;
                      ref
                          .read(layoutStateProvider.notifier)
                          .setChatWidthRatio(newRatio);
                    },
                    onDragEnd: () {
                      setState(() => _isDragging = false);
                      ref
                          .read(layoutStateProvider.notifier)
                          .commitChatWidthRatio();
                    },
                    onDoubleTap: () => ref
                        .read(layoutStateProvider.notifier)
                        .resetChatWidthRatio(),
                  ),
                  IgnorePointer(
                    ignoring: _isDragging,
                    child: SizedBox(
                      width: chatWidth,
                      child: const ChatPanel(),
                    ),
                  ),
                ],
{% endif %}              ],
            ),
{% if include_chat %}          ),
{% endif %}        );
      },
    );
  }
}

// ============================================================
// MEDIUM (600-840px): DocTreeNav + article; TocPanel as modal
// ============================================================
class _MediumLayout extends ConsumerWidget {
  const _MediumLayout({
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.body,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final Widget body;

  void _showToc(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => DraggableScrollableSheet(
        initialChildSize: 0.6,
        minChildSize: 0.3,
        maxChildSize: 0.9,
        expand: false,
        builder: (context, _) =>
            TocPanel(onClose: () => Navigator.of(context).maybePop()),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
{% if include_chat %}    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;
{% endif %}
    return Scaffold(
{% if include_chat %}      endDrawer: SizedBox(
        width: layoutExt.chatDrawerWidth,
        child: const Drawer(child: ChatPanel(isFullScreen: true)),
      ),
{% endif %}      body: Row(
        children: [
          DocTreeNav(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
            collapsed: true,
          ),
          Expanded(
            child: Column(
              children: [
                _ArticleHeader(onShowToc: () => _showToc(context)),
                Expanded(
                  child: _ArticleArea(child: body),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ============================================================
// COMPACT (< 600px): article + tree drawer + bottom nav; modal chat
// ============================================================
class _CompactLayout extends ConsumerWidget {
  const _CompactLayout({
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.body,
  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final Widget body;

  static final _destinations = navDestinations
      .map(
        (d) => NavigationDestination(
          icon: Icon(d.icon),
          selectedIcon: Icon(d.selectedIcon),
          label: d.label,
        ),
      )
      .toList(growable: false);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      drawer: DocTreeNav.drawer(
        selectedIndex: selectedIndex,
        onDestinationSelected: onDestinationSelected,
      ),
      body: Builder(
        builder: (context) => Column(
          children: [
            SizedBox(
              height: DesignTokens.workingAreaHeaderHeight,
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.menu),
                    onPressed: () => Scaffold.of(context).openDrawer(),
                    tooltip: 'Open navigation menu',
                  ),
                  const Expanded(child: _ArticleHeader()),
                ],
              ),
            ),
            Expanded(child: _ArticleArea(child: body)),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex,
        onDestinationSelected: onDestinationSelected,
        destinations: _destinations,
      ),
    );
  }
}
