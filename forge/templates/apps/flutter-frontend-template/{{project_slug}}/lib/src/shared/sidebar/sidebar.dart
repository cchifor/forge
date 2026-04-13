import 'package:flutter/material.dart';

import 'sidebar_body.dart';
import 'sidebar_controller.dart';
import 'sidebar_data.dart';

/// A builder function that returns [SidebarData] based on the current state.
typedef SidebarBuilder = SidebarData Function(SidebarBuilderData data);

/// A lite, reusable sidebar widget with collapse/expand animation.
///
/// Inspired by `flutter_side_menu`, simplified for this application:
/// - No manual resizer (handled by external splitter)
/// - No left/right positioning (always left)
/// - Builder pattern for reactive item construction
/// - Controlled via [SidebarController] or `isOpen` prop
class Sidebar extends StatefulWidget {
  const Sidebar({
    required this.builder,
    this.controller,
    this.minWidth = 72,
    this.maxWidth = 240,
    this.isOpen = true,
    this.backgroundColor,
    this.border,
    this.animationDuration = const Duration(milliseconds: 200),
    this.animationCurve = Curves.easeInOutCubic,
    super.key,
  });

  /// Builder function returning [SidebarData] for the current state.
  final SidebarBuilder builder;

  /// Optional controller for programmatic open/close/toggle.
  /// When provided, the widget listens to controller changes.
  final SidebarController? controller;

  /// Width when collapsed (icon-only mode).
  final double minWidth;

  /// Width when expanded (full labels visible).
  final double maxWidth;

  /// Initial open state (ignored if controller is provided).
  final bool isOpen;

  /// Background color. Defaults to `theme.colorScheme.surfaceContainerLow`.
  final Color? backgroundColor;

  /// Optional right border when expanded.
  final BoxBorder? border;

  /// Duration of the width animation.
  final Duration animationDuration;

  /// Curve of the width animation.
  final Curve animationCurve;

  @override
  State<Sidebar> createState() => _SidebarState();
}

class _SidebarState extends State<Sidebar> {
  late bool _isOpen;

  @override
  void initState() {
    super.initState();
    _isOpen = widget.controller?.isOpen ?? widget.isOpen;
    widget.controller?.addListener(_onControllerChanged);
  }

  @override
  void didUpdateWidget(covariant Sidebar oldWidget) {
    super.didUpdateWidget(oldWidget);

    // Controller changed
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller?.removeListener(_onControllerChanged);
      widget.controller?.addListener(_onControllerChanged);
      if (widget.controller != null) {
        _isOpen = widget.controller!.isOpen;
      }
    }

    // Prop-driven (no controller)
    if (widget.controller == null && widget.isOpen != oldWidget.isOpen) {
      _isOpen = widget.isOpen;
    }
  }

  @override
  void dispose() {
    widget.controller?.removeListener(_onControllerChanged);
    super.dispose();
  }

  void _onControllerChanged() {
    setState(() => _isOpen = widget.controller!.isOpen);
  }

  double get _currentWidth => _isOpen ? widget.maxWidth : widget.minWidth;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final reducedMotion = MediaQuery.of(context).disableAnimations;
    final bgColor =
        widget.backgroundColor ?? theme.colorScheme.surfaceContainerLow;

    final builderData = SidebarBuilderData(
      isOpen: _isOpen,
      currentWidth: _currentWidth,
      minWidth: widget.minWidth,
      maxWidth: widget.maxWidth,
    );

    final data = widget.builder(builderData);

    return Semantics(
      label: 'Main navigation',
      explicitChildNodes: true,
      child: RepaintBoundary(
        child: AnimatedContainer(
          duration: reducedMotion ? Duration.zero : widget.animationDuration,
          curve: widget.animationCurve,
          width: _currentWidth,
          clipBehavior: Clip.hardEdge,
          decoration: BoxDecoration(
            color: bgColor,
            border: _isOpen ? widget.border : null,
          ),
          child: SidebarBody(data: data, isOpen: _isOpen),
        ),
      ),
    );
  }
}
