import 'package:flutter/material.dart';

class AiThemeColors extends ThemeExtension<AiThemeColors> {
  const AiThemeColors({
    required this.gradientStart,
    required this.gradientEnd,
    required this.aiSurface,
    required this.aiOnSurface,
    required this.aiInputGlow,
  });

  /// Purple accent for AI gradient start
  final Color gradientStart;

  /// Cyan accent for AI gradient end
  final Color gradientEnd;

  /// Tinted surface for AI chat panel background
  final Color aiSurface;

  /// Text color on AI surfaces
  final Color aiOnSurface;

  /// Pulsing glow color for AI input during generation
  final Color aiInputGlow;

  LinearGradient get gradient => LinearGradient(
        colors: [gradientStart, gradientEnd],
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
      );

  // --- Presets ---

  static const light = AiThemeColors(
    gradientStart: Color(0xFF7C3AED),
    gradientEnd: Color(0xFF06B6D4),
    aiSurface: Color(0xFFF5F3FF),
    aiOnSurface: Color(0xFF1E1B4B),
    aiInputGlow: Color(0x407C3AED),
  );

  static const dark = AiThemeColors(
    gradientStart: Color(0xFF8B5CF6),
    gradientEnd: Color(0xFF22D3EE),
    aiSurface: Color(0xFF1A1625),
    aiOnSurface: Color(0xFFE8E5F0),
    aiInputGlow: Color(0x408B5CF6),
  );

  static const oled = AiThemeColors(
    gradientStart: Color(0xFFA78BFA),
    gradientEnd: Color(0xFF67E8F9),
    aiSurface: Color(0xFF0A0812),
    aiOnSurface: Color(0xFFE8E5F0),
    aiInputGlow: Color(0x40A78BFA),
  );

  @override
  AiThemeColors copyWith({
    Color? gradientStart,
    Color? gradientEnd,
    Color? aiSurface,
    Color? aiOnSurface,
    Color? aiInputGlow,
  }) {
    return AiThemeColors(
      gradientStart: gradientStart ?? this.gradientStart,
      gradientEnd: gradientEnd ?? this.gradientEnd,
      aiSurface: aiSurface ?? this.aiSurface,
      aiOnSurface: aiOnSurface ?? this.aiOnSurface,
      aiInputGlow: aiInputGlow ?? this.aiInputGlow,
    );
  }

  @override
  AiThemeColors lerp(covariant AiThemeColors? other, double t) {
    if (other == null) return this;
    return AiThemeColors(
      gradientStart: Color.lerp(gradientStart, other.gradientStart, t)!,
      gradientEnd: Color.lerp(gradientEnd, other.gradientEnd, t)!,
      aiSurface: Color.lerp(aiSurface, other.aiSurface, t)!,
      aiOnSurface: Color.lerp(aiOnSurface, other.aiOnSurface, t)!,
      aiInputGlow: Color.lerp(aiInputGlow, other.aiInputGlow, t)!,
    );
  }
}
