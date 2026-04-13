import 'package:flutter/material.dart';

import 'sidebar_item.dart';

/// Renders a [SidebarItemTitle] as a non-interactive section header.
///
/// Hidden when the sidebar is collapsed (text wouldn't fit).
class SidebarItemTitleWidget extends StatelessWidget {
  const SidebarItemTitleWidget({
    required this.item,
    required this.isOpen,
    super.key,
  });

  final SidebarItemTitle item;
  final bool isOpen;

  @override
  Widget build(BuildContext context) {
    if (!isOpen) return const SizedBox.shrink();

    final theme = Theme.of(context);
    return Padding(
      padding: item.padding,
      child: Text(
        item.title,
        style: item.titleStyle ??
            theme.textTheme.labelSmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
            ),
        overflow: TextOverflow.ellipsis,
        maxLines: 1,
      ),
    );
  }
}
