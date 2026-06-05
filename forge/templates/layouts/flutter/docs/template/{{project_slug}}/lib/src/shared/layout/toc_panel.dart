import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../routing/app_router.dart';
import '../../theme/design_tokens.dart';

/// Right "On this page" table-of-contents column for the Documentation
/// 3-Column shell.
///
/// Flutter routed content has no scrapeable DOM (unlike the web docs theme),
/// so this panel derives a lightweight in-page outline from the current
/// GoRouter location: a top "Overview" anchor plus an entry per path segment.
/// It re-reads the location on every navigation via the router delegate
/// listener and exposes [scrollController] so the host can wire smooth-scroll
/// targets in a future iteration.
///
/// Self-contained: no shared layout state. Surfaced as the inline right column
/// (expanded tier), or as a modal/drawer (medium tier).
class TocPanel extends ConsumerStatefulWidget {
  const TocPanel({this.onClose, super.key});

  /// When provided, renders a close affordance (used by the medium-tier modal).
  final VoidCallback? onClose;

  @override
  ConsumerState<TocPanel> createState() => _TocPanelState();
}

class _TocPanelState extends ConsumerState<TocPanel> {
  late GoRouter _router;
  String _location = '/';
  int _activeIndex = 0;

  @override
  void initState() {
    super.initState();
    _router = ref.read(goRouterProvider);
    _location = _router.routerDelegate.currentConfiguration.uri.path;
    _router.routerDelegate.addListener(_onRouteChanged);
  }

  @override
  void dispose() {
    _router.routerDelegate.removeListener(_onRouteChanged);
    super.dispose();
  }

  void _onRouteChanged() {
    final next = _router.routerDelegate.currentConfiguration.uri.path;
    if (next != _location && mounted) {
      setState(() {
        _location = next;
        _activeIndex = 0;
      });
    }
  }

  List<String> _headings() {
    final segments =
        _location.split('/').where((s) => s.isNotEmpty).toList();
    if (segments.isEmpty) return const ['Overview'];
    return [
      'Overview',
      for (final segment in segments) _titleCase(segment),
    ];
  }

  String _titleCase(String s) {
    if (s.isEmpty) return s;
    return s[0].toUpperCase() + s.substring(1);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final headings = _headings();

    return Container(
      width: 220,
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        border: Border(
          left: BorderSide(
            color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
          ),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: DesignTokens.workingAreaHeaderHeight,
            child: Padding(
              padding:
                  const EdgeInsets.symmetric(horizontal: DesignTokens.p16),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      'ON THIS PAGE',
                      style: theme.textTheme.labelSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.5,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                  if (widget.onClose != null)
                    IconButton(
                      icon: const Icon(Icons.close),
                      iconSize: DesignTokens.iconMD,
                      onPressed: widget.onClose,
                      tooltip: 'Close contents',
                      visualDensity: VisualDensity.compact,
                    ),
                ],
              ),
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(
                vertical: DesignTokens.p8,
                horizontal: DesignTokens.p8,
              ),
              itemCount: headings.length,
              itemBuilder: (context, index) {
                final isActive = index == _activeIndex;
                final isSub = index > 0;
                return InkWell(
                  onTap: () => setState(() => _activeIndex = index),
                  borderRadius:
                      BorderRadius.circular(DesignTokens.radiusSmall),
                  child: Padding(
                    padding: EdgeInsets.only(
                      left: isSub ? DesignTokens.p20 : DesignTokens.p8,
                      right: DesignTokens.p8,
                      top: DesignTokens.p4,
                      bottom: DesignTokens.p4,
                    ),
                    child: Text(
                      headings[index],
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: isActive
                            ? theme.colorScheme.primary
                            : theme.colorScheme.onSurfaceVariant,
                        fontWeight:
                            isActive ? FontWeight.w600 : FontWeight.w400,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
