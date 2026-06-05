import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../theme/design_tokens.dart';
import '../../theme/layout_theme_extension.dart';
import 'app_sidebar.dart';
import 'breadcrumb_bar.dart';
import 'layout_state.dart';
import 'nav_destinations.dart';
{% if include_chat %}import '../widgets/chat_button.dart';
import 'right_panel.dart';
import 'vertical_split_handle.dart';
{% endif %}
/// Three-Pane + Right Agent Panel shell.
///
/// Chassis = base [AppSidebar] (left) + a content column.
{% if include_chat %}///
/// The differentiator is a persistent right Agent Panel ([RightPanel]) that
/// hosts the AI chat surface: an inline resizable pane at the expanded
/// breakpoint, an end-drawer at medium, and a modal bottom sheet at compact
/// (the last two are surfaced through the shared [ChatButton] in the content
/// header).
{% else %}///
/// With chat disabled the shell is a plain two-pane sidebar + content layout;
/// the right Agent Panel, its imports, and the header chat button are all
/// Jinja-gated away at generation time.
{% endif %}class AppLayoutShell extends HookConsumerWidget {
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
{% if include_chat %}            layout: layout,
{% endif %}          ),
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

/// Content header: breadcrumbs on the left and (when chat is enabled) the
/// shared [ChatButton] on the right. Defined locally instead of reusing
/// `WorkingAreaHeader` because the base only strips that widget's chat button
/// for the `sidebar` layout; here the button is Jinja-gated directly.
class _ContentHeader extends StatelessWidget {
  const _ContentHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      height: DesignTokens.workingAreaHeaderHeight,
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p16),
      child: const Row(
        children: [
          BreadcrumbBar(),
          Spacer(),
{% if include_chat %}          ChatButton(),
{% endif %}        ],
      ),
    );
  }
}

/// Center column shared by every breakpoint: content header + routed body.
class _ContentColumn extends StatelessWidget {
  const _ContentColumn({required this.body});

  final Widget body;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const _ContentHeader(),
        Expanded(child: body),
      ],
    );
  }
}

// ============================================================
// EXPANDED (>= 840px): Sidebar + Content + persistent right Agent Panel
// ============================================================
class _ExpandedLayout extends ConsumerStatefulWidget {
  const _ExpandedLayout({
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.body,
{% if include_chat %}    required this.layout,
{% endif %}  });

  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final Widget body;
{% if include_chat %}  final LayoutState layout;
{% endif %}

  @override
  ConsumerState<_ExpandedLayout> createState() => _ExpandedLayoutState();
}

class _ExpandedLayoutState extends ConsumerState<_ExpandedLayout> {
{% if include_chat %}  bool _isDragging = false;
{% endif %}
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
{% if include_chat %}    final layout = widget.layout;
    final layoutExt = theme.extension<LayoutThemeExtension>()!;
{% endif %}
    return LayoutBuilder(
      builder: (context, constraints) {
{% if include_chat %}        final availableWidth =
            constraints.maxWidth - layout.effectiveSidebarWidth;
        final maxPanelWidth = availableWidth - layoutExt.minMainAreaWidth;
        final panelWidth = layout.chatInline
            ? (layout.chatWidthRatio * availableWidth).clamp(
                layoutExt.minChatWidth,
                maxPanelWidth.clamp(layoutExt.minChatWidth, double.infinity),
              )
            : 0.0;
{% endif %}
        return Material(
          color: theme.scaffoldBackgroundColor,
          child: MouseRegion(
{% if include_chat %}            cursor: _isDragging
                ? SystemMouseCursors.resizeColumn
                : MouseCursor.defer,
{% endif %}            child: Row(
              children: [
                // Left navigation rail (base collapsible sidebar).
                AppSidebar(
                  selectedIndex: widget.selectedIndex,
                  onDestinationSelected: widget.onDestinationSelected,
                ),

                // Center content column (fills remaining space).
                Expanded(
{% if include_chat %}                  child: IgnorePointer(
                    ignoring: _isDragging,
                    child: _ContentColumn(body: widget.body),
                  ),
{% else %}                  child: _ContentColumn(body: widget.body),
{% endif %}                ),
{% if include_chat %}
                // Splitter + persistent right Agent Panel (explicit width).
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
                      width: panelWidth,
                      child: RightPanel(
                        onClose: () => ref
                            .read(layoutStateProvider.notifier)
                            .setChatPanelOpen(false),
                      ),
                    ),
                  ),
                ],
{% endif %}              ],
            ),
          ),
        );
      },
    );
  }
}

// ============================================================
// MEDIUM (600-840px): Collapsed Sidebar + Content + endDrawer Agent Panel
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

  @override
  Widget build(BuildContext context, WidgetRef ref) {
{% if include_chat %}    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;

{% endif %}    return Scaffold(
{% if include_chat %}      // ChatButton (medium tier) opens this endDrawer; the right Agent Panel
      // rides in as a drawer at this breakpoint.
      endDrawer: SizedBox(
        width: layoutExt.chatDrawerWidth,
        child: Drawer(
          child: RightPanel(
            isFullScreen: true,
            onClose: () => Navigator.of(context).maybePop(),
          ),
        ),
      ),
{% endif %}      body: Row(
        children: [
          AppSidebar(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
          ),
          Expanded(child: _ContentColumn(body: body)),
        ],
      ),
    );
  }
}

// ============================================================
// COMPACT (< 600px): Bottom NavigationBar + modal Agent Panel
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
    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;

    return Scaffold(
      body: Column(
        children: [
          SizedBox(
            height: layoutExt.headerHeight,
            child: const _ContentHeader(),
          ),
          Expanded(child: body),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex,
        onDestinationSelected: onDestinationSelected,
        destinations: _destinations,
      ),
    );
  }
}
