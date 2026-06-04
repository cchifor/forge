import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

{% if include_chat %}import '../../features/chat/presentation/chat_panel.dart';
{% endif %}import '../../theme/layout_theme_extension.dart';
import 'bottom_tab_bar.dart';
import 'layout_state.dart';
import 'nav_rail.dart';
{% if include_chat %}import 'vertical_split_handle.dart';
{% endif %}import 'working_area_header.dart';

/// Tab Bar App Shell.
///
/// Touch-first primary nav that promotes across tiers:
///   compact  (<600px)  -> bottom [BottomTabBar] (NavigationBar)
///   medium   (600-840) -> icon-only [NavRail]   (NavigationRail)
///   expanded (>=840px) -> extended [NavRail]    (NavigationRail + labels)
///
/// Chat (when included) follows the shared three-mode pattern:
///   expanded -> inline resizable pane (VerticalSplitHandle + ChatPanel)
///   medium   -> Scaffold.endDrawer (opened by ChatButton in the header)
///   compact  -> modal bottom sheet (opened by ChatButton in the header)
///
/// Reuses the base [WorkingAreaHeader] (breadcrumbs + chat button), the shared
/// [LayoutState] breakpoints, the shared [navDestinations] (via the region
/// widgets) and the base chat widgets. Keeps the
/// `AppLayoutShell(navigationShell, selectedIndex, onDestinationSelected)` API.
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
// EXPANDED (>= 840px): Extended NavRail + Working Area + Inline Chat
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
  {% if include_chat %}bool _isDragging = false;
{% endif %}
  @override
  Widget build(BuildContext context) {
    final layout = widget.layout;
    final theme = Theme.of(context);
    {% if include_chat %}final layoutExt = theme.extension<LayoutThemeExtension>()!;
{% endif %}
    return LayoutBuilder(
      builder: (context, constraints) {
        {% if include_chat %}final availableWidth =
            constraints.maxWidth - layout.effectiveSidebarWidth;
        final maxChatWidth = availableWidth - layoutExt.minMainAreaWidth;
        final chatWidth = layout.chatInline
            ? (layout.chatWidthRatio * availableWidth).clamp(
                layoutExt.minChatWidth,
                maxChatWidth.clamp(layoutExt.minChatWidth, double.infinity),
              )
            : 0.0;

        {% endif %}return Material(
          color: theme.scaffoldBackgroundColor,
          child: MouseRegion(
            {% if include_chat %}cursor: _isDragging
                ? SystemMouseCursors.resizeColumn
                : MouseCursor.defer,
            {% endif %}child: Row(
              children: [
                // Extended NavigationRail (icons + labels)
                NavRail(
                  selectedIndex: widget.selectedIndex,
                  onDestinationSelected: widget.onDestinationSelected,
                  extended: true,
                ),

                // Working area (fills remaining space)
                Expanded(
                  child: {% if include_chat %}IgnorePointer(
                    ignoring: _isDragging,
                    child: {% endif %}Column(
                    children: [
                      const WorkingAreaHeader(),
                      Expanded(child: widget.body),
                    ],
                  ),
                  {% if include_chat %}),
                {% endif %}),

                {% if include_chat %}// Splitter + Chat panel (explicit width)
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
                {% endif %}],
            ),
          ),
        );
      },
    );
  }
}

// ============================================================
// MEDIUM (600-840px): Icon-only NavRail + Working Area + endDrawer
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
    {% if include_chat %}final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;

    {% endif %}return Scaffold(
      {% if include_chat %}// ChatButton at the medium tier opens this endDrawer.
      endDrawer: SizedBox(
        width: layoutExt.chatDrawerWidth,
        child: const Drawer(child: ChatPanel(isFullScreen: true)),
      ),
      {% endif %}body: Row(
        children: [
          NavRail(
            selectedIndex: selectedIndex,
            onDestinationSelected: onDestinationSelected,
            extended: false,
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
// COMPACT (< 600px): Bottom Tab Bar + Modal Chat
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

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final layoutExt =
        Theme.of(context).extension<LayoutThemeExtension>()!;

    return Scaffold(
      body: Column(
        children: [
          SizedBox(
            height: layoutExt.headerHeight,
            // WorkingAreaHeader carries the ChatButton, which at the compact
            // tier opens chat as a modal bottom sheet.
            child: const WorkingAreaHeader(),
          ),
          Expanded(child: body),
        ],
      ),
      bottomNavigationBar: BottomTabBar(
        selectedIndex: selectedIndex,
        onDestinationSelected: onDestinationSelected,
      ),
    );
  }
}
