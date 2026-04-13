import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../routing/app_router.dart';
import '../../theme/design_tokens.dart';

/// Displays breadcrumb navigation derived from the current GoRouter location.
///
/// Uses [GoRouter.routerDelegate] listener via a [ConsumerStatefulWidget]
/// to reliably track all navigation changes including back/pop within
/// shell branches.
class BreadcrumbBar extends ConsumerStatefulWidget {
  const BreadcrumbBar({super.key});

  @override
  ConsumerState<BreadcrumbBar> createState() => _BreadcrumbBarState();
}

class _BreadcrumbBarState extends ConsumerState<BreadcrumbBar> {
  static const _topLevelPaths = {'profile', 'settings'};

  static const _segmentNames = {
    '': 'Home',
    // --- feature breadcrumb names ---
    'profile': 'Profile',
    'settings': 'Settings',
  };

  late GoRouter _router;
  String _location = '/';

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
    final newLocation =
        _router.routerDelegate.currentConfiguration.uri.path;
    if (newLocation != _location && mounted) {
      setState(() => _location = newLocation);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final segments =
        _location.split('/').where((s) => s.isNotEmpty).toList();

    // Root "/"
    if (segments.isEmpty) {
      return _currentPageLabel('Home', theme);
    }

    // Top-level branch ("/items", "/profile", "/settings")
    if (segments.length == 1 && _topLevelPaths.contains(segments[0])) {
      return _currentPageLabel(_displayName(segments[0]), theme);
    }

    // Nested route ("/items/new", "/items/:id")
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < segments.length; i++) ...[
          if (i > 0)
            Icon(
              Icons.chevron_right,
              size: DesignTokens.iconSM,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          if (i == segments.length - 1)
            _currentPageLabel(_displayName(segments[i]), theme)
          else
            _BreadcrumbLink(
              label: _displayName(segments[i]),
              onTap: () => context.go(
                '/${segments.sublist(0, i + 1).join('/')}',
              ),
              theme: theme,
            ),
        ],
      ],
    );
  }

  Widget _currentPageLabel(String label, ThemeData theme) {
    return Text(
      label,
      style: theme.textTheme.titleSmall?.copyWith(
        fontWeight: FontWeight.w600,
      ),
    );
  }

  String _displayName(String segment) {
    return _segmentNames[segment] ?? _titleCase(segment);
  }

  String _titleCase(String s) {
    if (s.isEmpty) return s;
    return s[0].toUpperCase() + s.substring(1);
  }
}

class _BreadcrumbLink extends StatelessWidget {
  const _BreadcrumbLink({
    required this.label,
    required this.onTap,
    required this.theme,
  });

  final String label;
  final VoidCallback onTap;
  final ThemeData theme;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(DesignTokens.p4),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: DesignTokens.p4,
          vertical: 2,
        ),
        child: Text(
          label,
          style: theme.textTheme.titleSmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ),
    );
  }
}
