import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
import '../../theme/layout_theme_extension.dart';

class VerticalSplitHandle extends StatefulWidget {
  const VerticalSplitHandle({
    required this.onDragStart,
    required this.onDragUpdate,
    required this.onDragEnd,
    required this.onDoubleTap,
    super.key,
  });

  final VoidCallback onDragStart;
  final ValueChanged<double> onDragUpdate;
  final VoidCallback onDragEnd;
  final VoidCallback onDoubleTap;

  @override
  State<VerticalSplitHandle> createState() => _VerticalSplitHandleState();
}

class _VerticalSplitHandleState extends State<VerticalSplitHandle> {
  bool _isHovered = false;
  bool _isDragging = false;

  bool get _active => _isHovered || _isDragging;

  void _endDrag() {
    setState(() => _isDragging = false);
    widget.onDragEnd();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final layoutExt = theme.extension<LayoutThemeExtension>()!;
    final dividerColor = _active
        ? theme.colorScheme.primary
        : theme.colorScheme.outlineVariant.withValues(alpha: 0.4);

    return MouseRegion(
      cursor: SystemMouseCursors.resizeColumn,
      onEnter: (_) => setState(() => _isHovered = true),
      onExit: (_) => setState(() => _isHovered = false),
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onHorizontalDragStart: (_) {
          setState(() => _isDragging = true);
          widget.onDragStart();
        },
        onHorizontalDragUpdate: (details) {
          widget.onDragUpdate(details.globalPosition.dx);
        },
        onHorizontalDragEnd: (_) => _endDrag(),
        onHorizontalDragCancel: _endDrag,
        onDoubleTap: widget.onDoubleTap,
        child: SizedBox(
          width: layoutExt.splitterWidth,
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: DesignTokens.durationNormal),
              width: _active ? 3 : 1,
              height: double.infinity,
              decoration: BoxDecoration(
                color: dividerColor,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
