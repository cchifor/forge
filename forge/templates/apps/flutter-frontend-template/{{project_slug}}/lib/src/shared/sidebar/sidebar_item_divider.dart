import 'package:flutter/material.dart';

import 'sidebar_item.dart';

/// Renders a [SidebarItemDivider] as a horizontal line separator.
class SidebarItemDividerWidget extends StatelessWidget {
  const SidebarItemDividerWidget({required this.item, super.key});

  final SidebarItemDivider item;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: item.padding,
      child: Divider(
        height: 1,
        thickness: item.thickness,
        color: item.color,
      ),
    );
  }
}
