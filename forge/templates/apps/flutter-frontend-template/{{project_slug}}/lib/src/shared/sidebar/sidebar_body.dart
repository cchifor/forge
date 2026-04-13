import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
import 'sidebar_data.dart';
import 'sidebar_item.dart';
import 'sidebar_item_divider.dart';
import 'sidebar_item_tile.dart';
import 'sidebar_item_title.dart';

/// Internal layout widget that arranges header, items, bottomItems, and footer.
///
/// All sections share the same [DesignTokens.sidebarBodyPadding] horizontal
/// inset so that icons align vertically across header, items, and footer.
class SidebarBody extends StatelessWidget {
  const SidebarBody({
    required this.data,
    required this.isOpen,
    super.key,
  });

  final SidebarData data;
  final bool isOpen;

  static const _hPad = DesignTokens.sidebarBodyPadding;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Header
        if (data.header != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: _hPad),
            child: data.header!,
          ),

        // Primary items (scrollable)
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: _hPad),
            itemCount: data.items.length,
            itemBuilder: (context, index) =>
                _buildItem(data.items[index]),
          ),
        ),

        // Bottom items (pinned above footer)
        if (data.bottomItems.isNotEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: _hPad),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final item in data.bottomItems) _buildItem(item),
              ],
            ),
          ),

        // Footer
        if (data.footer != null)
          Padding(
            padding: const EdgeInsets.only(
              left: _hPad,
              right: _hPad,
              bottom: DesignTokens.p8,
            ),
            child: data.footer!,
          ),
      ],
    );
  }

  Widget _buildItem(SidebarItem item) => switch (item) {
        SidebarItemTile() => SidebarItemTileWidget(
            item: item,
            isOpen: isOpen,
            defaults: data.tileDefaults,
          ),
        SidebarItemTitle() => SidebarItemTitleWidget(
            item: item,
            isOpen: isOpen,
          ),
        SidebarItemDivider() => SidebarItemDividerWidget(item: item),
      };
}
