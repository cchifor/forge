import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../features/chat/presentation/chat_panel.dart';
import '../../theme/layout_theme_extension.dart';
import 'app_sidebar.dart';
import 'layout_state.dart';
import 'nav_destinations.dart';
import 'vertical_split_handle.dart';
import 'working_area_header.dart';

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

// ============================================================
// EXPANDED (> 840px): Sidebar + Working Area + Inline Chat
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
  bool _isDragging = false;

  @override
  Widget build(BuildContext context) {
    final layout = widget.layout;
    final theme = Theme.of(context);
    final layoutExt = theme.extension<LayoutThemeExtension>()!;

    return LayoutBuilder(
      builder: (context, constraints) {
        final availableWidth =
            constraints.maxWidth - layout.effectiveSidebarWidth;
        final maxChatWidth = availableWidth - layoutExt.minMainAreaWidth;
        final chatWidth = layout.chatInline
            ? (layout.chatWidthRatio * availableWidth).clamp(
                layoutExt.minChatWidth,
                maxChatWidth.clamp(layoutExt.minChatWidth, double.infinity),
              )
            : 0.0;

        return Material(
          color: theme.scaffoldBackgroundColor,
          child: MouseRegion(
            cursor: _isDragging
                ? SystemMouseCursors.resizeColumn
                : MouseCursor.defer,
            child: Row(
              children: [
                // Custom collapsible sidebar
                AppSidebar(
                  selectedIndex: widget.selectedIndex,
                  onDestinationSelected: widget.onDestinationSelected,
                ),

                // Working area (fills remaining space)
                Expanded(
                  child: IgnorePointer(
                    ignoring: _isDragging,
                    child: Column(
                      children: [
                        const WorkingAreaHeader(),
                        Expanded(child: widget.body),
                      ],
                    ),
                  ),
                ),

                // Splitter + Chat panel (explicit width)
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
              ],
            ),
          ),
        );
      },
    );
  }
}

// ============================================================
// MEDIUM (600-840px): Collapsed Sidebar + Working Area + endDrawer
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
    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;

    return Scaffold(
      endDrawer: SizedBox(
        width: layoutExt.chatDrawerWidth,
        child: const Drawer(child: ChatPanel(isFullScreen: true)),
      ),
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
                Expanded(child: body),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ============================================================
// COMPACT (< 600px): Bottom NavigationBar + Modal Chat
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
            child: const WorkingAreaHeader(),
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
