import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';

class PressableScale extends StatefulWidget {
  const PressableScale({
    required this.onPressed,
    required this.child,
    this.scale = 0.98,
    super.key,
  });

  final VoidCallback? onPressed;
  final Widget child;
  final double scale;

  @override
  State<PressableScale> createState() => _PressableScaleState();
}

class _PressableScaleState extends State<PressableScale> {
  bool _isPressed = false;

  @override
  Widget build(BuildContext context) {
    final reducedMotion = MediaQuery.of(context).disableAnimations;
    return GestureDetector(
      onTapDown: (_) => setState(() => _isPressed = true),
      onTapUp: (_) {
        setState(() => _isPressed = false);
        widget.onPressed?.call();
      },
      onTapCancel: () => setState(() => _isPressed = false),
      child: AnimatedScale(
        scale: _isPressed ? widget.scale : 1.0,
        duration: reducedMotion
            ? Duration.zero
            : const Duration(milliseconds: DesignTokens.durationFast),
        child: widget.child,
      ),
    );
  }
}
