import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

{% if include_chat %}import '../../features/chat/presentation/chat_panel.dart';
import '../../theme/layout_theme_extension.dart';
{% endif %}import 'app_footer.dart';
import 'layout_state.dart';
{% if include_chat %}import 'vertical_split_handle.dart';
{% endif %}import 'top_nav_bar.dart';
import 'top_nav_drawer.dart';

// --- feature nav items ---
// nav destinations are injected into nav_destinations.dart by the base
// post_generate; the TopNavBar / TopNavDrawer render them directly.

/// Top-Nav Content Shell.
///
/// A horizontal [TopNavBar] sits above a centered content column with no
/// persistent side rail. The primary nav is inline on the expanded tier and
/// collapses behind a hamburger ([TopNavDrawer]) on the medium and compact
/// tiers. Chat is surfaced as an inline resizable pane (expanded), an
/// endDrawer (medium), or a modal bottom sheet (compact).
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

/// Centered, max-width content area shared by every tier.
class _ContentArea extends StatelessWidget {
  const _ContentArea({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1280),
        child: child,
      ),
    );
  }
}

// ============================================================
// EXPANDED (> 840px): TopNavBar + Content + Footer + Inline Chat
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
                // Working area (fills remaining space)
                Expanded(
                  child: {% if include_chat %}IgnorePointer(
                    ignoring: _isDragging,
                    child: {% endif %}Column(
                      children: [
                        TopNavBar(
                          selectedIndex: widget.selectedIndex,
                          onDestinationSelected: widget.onDestinationSelected,
                          onMenuPressed: () {},
                        ),
                        Expanded(
                          child: _ContentArea(child: widget.body),
                        ),
                        const AppFooter(),
                      ],
                    ),
{% if include_chat %}                  ),
{% endif %}                ),

{% if include_chat %}                // Splitter + Chat panel (explicit width)
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
// MEDIUM (600-840px): TopNavBar(compact) + drawer + endDrawer chat
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
{% endif %}
    return Scaffold(
      drawer: TopNavDrawer(
        selectedIndex: selectedIndex,
        onDestinationSelected: onDestinationSelected,
      ),
{% if include_chat %}      endDrawer: SizedBox(
        width: layoutExt.chatDrawerWidth,
        child: const Drawer(child: ChatPanel(isFullScreen: true)),
      ),
{% endif %}      body: Builder(
        builder: (context) => Column(
          children: [
            TopNavBar(
              selectedIndex: selectedIndex,
              onDestinationSelected: onDestinationSelected,
              onMenuPressed: () => Scaffold.of(context).openDrawer(),
              compact: true,
            ),
            Expanded(
              child: _ContentArea(child: body),
            ),
            const AppFooter(),
          ],
        ),
      ),
    );
  }
}

// ============================================================
// COMPACT (< 600px): TopNavBar(compact) + drawer + modal chat
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
    return Scaffold(
      drawer: TopNavDrawer(
        selectedIndex: selectedIndex,
        onDestinationSelected: onDestinationSelected,
      ),
      body: Builder(
        builder: (context) => Column(
          children: [
            TopNavBar(
              selectedIndex: selectedIndex,
              onDestinationSelected: onDestinationSelected,
              onMenuPressed: () => Scaffold.of(context).openDrawer(),
              compact: true,
            ),
            Expanded(
              child: _ContentArea(child: body),
            ),
          ],
        ),
      ),
    );
  }
}
