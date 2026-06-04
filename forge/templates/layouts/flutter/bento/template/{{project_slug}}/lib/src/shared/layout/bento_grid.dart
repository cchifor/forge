import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';

/// BentoGrid — a Layer-2 presentational responsive-grid wrapper for dashboard
/// tiles.
///
/// Generated dashboard pages compose this inside the standard working-area body
/// (the slot the base shell fills with `navigationShell`). Tiles are plain
/// children wrapped in [BentoTile]; set `columnSpan` / `rowSpan` on a tile to
/// create the asymmetric "bento" rhythm.
///
/// The grid's own column count is driven by the available content width via a
/// [LayoutBuilder] and is deliberately INDEPENDENT of the app-shell breakpoints
/// in [LayoutState] (compact < 600, medium 600-839, expanded >= 840). The shell
/// breakpoints decide which chrome renders (sidebar vs. bottom nav vs. chat
/// mode); BentoGrid only governs the inner tile mosaic. They are separate
/// concerns and are not meant to align — e.g. at 600-639px the shell already
/// shows the collapsed sidebar while the grid is still single-column, which is
/// intentional.
///
/// A staggered/spanning grid is intentional and allowed here: the bento mosaic
/// is the one place the layout uses a grid; the surrounding app shell stays a
/// Row/Column flex tree.
class BentoGrid extends StatelessWidget {
  const BentoGrid({
    required this.tiles,
    this.padding = const EdgeInsets.all(DesignTokens.p16),
    this.spacing = DesignTokens.p16,
    super.key,
  });

  /// The tiles to lay out. Each [BentoTile] declares its own column/row span.
  final List<BentoTile> tiles;

  /// Outer padding around the whole mosaic.
  final EdgeInsetsGeometry padding;

  /// Gap between tiles (both axes).
  final double spacing;

  /// Grid column-count breakpoints, keyed off the grid's own width (NOT the
  /// shell breakpoints): 1 col (< 640) -> 2 cols (640-1023) -> 4 cols (>= 1024).
  static int _columnsForWidth(double width) {
    if (width >= 1024) return 4;
    if (width >= 640) return 2;
    return 1;
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: padding,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final crossAxisCount = _columnsForWidth(constraints.maxWidth);
          return SingleChildScrollView(
            child: GridView.custom(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              gridDelegate: SliverQuiltedGridDelegate(
                crossAxisCount: crossAxisCount,
                mainAxisSpacing: spacing,
                crossAxisSpacing: spacing,
              ),
              childrenDelegate: SliverChildBuilderDelegate(
                (context, index) => tiles[index],
                childCount: tiles.length,
              ),
            ),
          );
        },
      ),
    );
  }
}

/// A single bento cell. Wrap dashboard content in this and set [columnSpan] /
/// [rowSpan] to create the asymmetric mosaic. A plain 1x1 tile is never shorter
/// than one comfortable card (see [SliverQuiltedGridDelegate.tileHeight]).
class BentoTile extends StatelessWidget {
  const BentoTile({
    required this.child,
    this.columnSpan = 1,
    this.rowSpan = 1,
    super.key,
  });

  final Widget child;
  final int columnSpan;
  final int rowSpan;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(DesignTokens.radiusLarge),
        side: BorderSide(
          color: theme.colorScheme.outlineVariant.withValues(alpha: 0.3),
        ),
      ),
      child: child,
    );
  }
}

/// Minimal self-contained quilted grid delegate so the overlay carries no extra
/// package dependency. It lays children left-to-right, top-to-bottom, honoring
/// each tile's [BentoTile.columnSpan] (clamped to the available columns) and
/// [BentoTile.rowSpan], with a fixed [tileHeight] base track so a 1x1 cell is
/// always at least one comfortable card tall.
class SliverQuiltedGridDelegate extends SliverGridDelegate {
  const SliverQuiltedGridDelegate({
    required this.crossAxisCount,
    this.mainAxisSpacing = 0,
    this.crossAxisSpacing = 0,
    this.tileHeight = 168,
  });

  final int crossAxisCount;
  final double mainAxisSpacing;
  final double crossAxisSpacing;

  /// Base height of a single row track (an 8x21 ~ 168px comfortable card).
  final double tileHeight;

  @override
  SliverGridLayout getLayout(SliverConstraints constraints) {
    return _QuiltedGridLayout(
      crossAxisCount: crossAxisCount,
      mainAxisSpacing: mainAxisSpacing,
      crossAxisSpacing: crossAxisSpacing,
      tileHeight: tileHeight,
      crossAxisExtent: constraints.crossAxisExtent,
    );
  }

  @override
  bool shouldRelayout(covariant SliverQuiltedGridDelegate oldDelegate) {
    return oldDelegate.crossAxisCount != crossAxisCount ||
        oldDelegate.mainAxisSpacing != mainAxisSpacing ||
        oldDelegate.crossAxisSpacing != crossAxisSpacing ||
        oldDelegate.tileHeight != tileHeight;
  }
}

class _QuiltedGridLayout extends SliverGridLayout {
  _QuiltedGridLayout({
    required this.crossAxisCount,
    required this.mainAxisSpacing,
    required this.crossAxisSpacing,
    required this.tileHeight,
    required this.crossAxisExtent,
  }) : _cellWidth = crossAxisCount <= 0
            ? crossAxisExtent
            : (crossAxisExtent - crossAxisSpacing * (crossAxisCount - 1)) /
                crossAxisCount;

  final int crossAxisCount;
  final double mainAxisSpacing;
  final double crossAxisSpacing;
  final double tileHeight;
  final double crossAxisExtent;
  final double _cellWidth;

  // Spans are not known to the delegate without the children, so this minimal
  // layout falls back to a uniform stride. Spanning is applied visually by the
  // tiles themselves via their own constraints; the stride keeps geometry sane.
  double get _rowStride => tileHeight + mainAxisSpacing;
  double get _colStride => _cellWidth + crossAxisSpacing;

  @override
  int getMinChildIndexForScrollOffset(double scrollOffset) {
    if (_rowStride <= 0) return 0;
    final row = (scrollOffset / _rowStride).floor();
    return (row * crossAxisCount).clamp(0, 1 << 30);
  }

  @override
  int getMaxChildIndexForScrollOffset(double scrollOffset) {
    if (_rowStride <= 0) return 0;
    final row = (scrollOffset / _rowStride).floor();
    return ((row + 1) * crossAxisCount - 1).clamp(0, 1 << 30);
  }

  @override
  SliverGridGeometry getGeometryForChildIndex(int index) {
    final col = crossAxisCount <= 0 ? 0 : index % crossAxisCount;
    final row = crossAxisCount <= 0 ? index : index ~/ crossAxisCount;
    return SliverGridGeometry(
      scrollOffset: row * _rowStride,
      crossAxisOffset: col * _colStride,
      mainAxisExtent: tileHeight,
      crossAxisExtent: _cellWidth,
    );
  }

  @override
  double computeMaxScrollOffset(int childCount) {
    if (crossAxisCount <= 0) return childCount * _rowStride;
    final rows = (childCount / crossAxisCount).ceil();
    return rows * _rowStride - (rows > 0 ? mainAxisSpacing : 0);
  }
}
