import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

{% if include_chat %}
import '../../features/chat/presentation/chat_panel.dart';
{% endif %}
import '../../theme/layout_theme_extension.dart';
import 'app_sidebar.dart';
import 'layout_state.dart';
import 'nav_destinations.dart';
{% if include_chat %}
import 'vertical_split_handle.dart';
{% endif %}
import 'working_area_header.dart';

/// Bento Grid Dashboard shell.
///
/// Chassis = the base sidebar shell (AppSidebar + WorkingAreaHeader + tri-modal
/// chat). The differentiator is the working-area body: it is hosted on a subtle
/// "dashboard canvas" surface so routed pages built from `BentoGrid` read as a
/// cohesive tile mosaic. Routing, Riverpod state, nav, theme and chat all come
/// from the base — this file only re-arranges the regions.
///
/// Breakpoint tiers mirror the base:
///   expanded (>= 840) — sidebar + canvas + inline resizable chat pane
///   medium   (600-839) — collapsed sidebar + canvas + endDrawer chat
///   compact  (< 600)   — canvas + bottom NavigationBar + modal chat
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

/// Wraps the routed body in the dashboard "canvas" surface shared by all tiers.
class _DashboardCanvas extends StatelessWidget {
  const _DashboardCanvas({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ColoredBox(
      color: theme.colorScheme.surfaceContainerLowest,
      child: child,
    );
  }
}

// ============================================================
// EXPANDED (>= 840px): Sidebar + Bento Canvas + Inline Chat
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
{% if include_chat %}
  bool _isDragging = false;
{% endif %}

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
{% if include_chat %}
    final layout = widget.layout;
    final layoutExt = theme.extension<LayoutThemeExtension>()!;
{% endif %}

    return LayoutBuilder(
      builder: (context, constraints) {
{% if include_chat %}
        final availableWidth =
            constraints.maxWidth - layout.effectiveSidebarWidth;
        final maxChatWidth = availableWidth - layoutExt.minMainAreaWidth;
        final chatWidth = layout.chatInline
            ? (layout.chatWidthRatio * availableWidth).clamp(
                layoutExt.minChatWidth,
                maxChatWidth.clamp(layoutExt.minChatWidth, double.infinity),
              )
            : 0.0;
{% endif %}

        return Material(
          color: theme.scaffoldBackgroundColor,
          child: MouseRegion(
{% if include_chat %}
            cursor: _isDragging
                ? SystemMouseCursors.resizeColumn
                : MouseCursor.defer,
{% endif %}
            child: Row(
              children: [
                // Custom collapsible sidebar (base chassis).
                AppSidebar(
                  selectedIndex: widget.selectedIndex,
                  onDestinationSelected: widget.onDestinationSelected,
                ),

                // Working area: header + bento dashboard canvas.
                Expanded(
                  child: IgnorePointer(
{% if include_chat %}
                    ignoring: _isDragging,
{% else %}
                    ignoring: false,
{% endif %}
                    child: Column(
                      children: [
                        const WorkingAreaHeader(),
                        Expanded(
                          child: _DashboardCanvas(child: widget.body),
                        ),
                      ],
                    ),
                  ),
                ),

{% if include_chat %}
                // Splitter + inline chat pane (explicit width).
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
{% endif %}
              ],
            ),
          ),
        );
      },
    );
  }
}

// ============================================================
// MEDIUM (600-840px): Collapsed Sidebar + Bento Canvas + endDrawer
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
{% if include_chat %}
    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;
{% endif %}

    return Scaffold(
{% if include_chat %}
      endDrawer: SizedBox(
        width: layoutExt.chatDrawerWidth,
        child: const Drawer(child: ChatPanel(isFullScreen: true)),
      ),
{% endif %}
      body: Row(
        children: [
          AppSidebar(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
          ),
          Expanded(
            child: Column(
              children: [
                const WorkingAreaHeader(),
                Expanded(child: _DashboardCanvas(child: body)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ============================================================
// COMPACT (< 600px): Bento Canvas + Bottom NavigationBar + Modal Chat
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

  static final _destinations = [
    // --- feature nav items ---
    for (final dest in navDestinations)
      NavigationDestination(
        icon: Icon(dest.icon),
        selectedIcon: Icon(dest.selectedIcon),
        label: dest.label,
      ),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;

    return Scaffold(
      body: Column(
        children: [
          SizedBox(
            height: layoutExt.headerHeight,
            child: const WorkingAreaHeader(),
          ),
          Expanded(child: _DashboardCanvas(child: body)),
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
