import 'package:flutter/material.dart';

/// shadcn-flavored theme for forge-generated Flutter applications.
///
/// Matches the design language of @forge/canvas-vue (shadcn-vue) and
/// @forge/canvas-svelte (bits-ui + shadcn-svelte). Phase 3.3 scaffold:
/// covers color roles, typography, and button shapes; full component
/// parity (Dialog, Dropdown, Toast, Badge) lands with the canvas
/// extraction PR.
class ForgeTheme {
  static ThemeData light({Color seed = const Color(0xFF2563EB)}) {
    final scheme = ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.light);
    return _build(scheme);
  }

  static ThemeData dark({Color seed = const Color(0xFF2563EB)}) {
    final scheme = ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark);
    return _build(scheme);
  }

  static ThemeData _build(ColorScheme scheme) {
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      textTheme: _textTheme(scheme),
      cardTheme: CardTheme(
        elevation: 0,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: scheme.outlineVariant),
          borderRadius: BorderRadius.circular(12),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          side: BorderSide(color: scheme.outline),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: scheme.outline),
        ),
      ),
    );
  }

  static TextTheme _textTheme(ColorScheme scheme) {
    // Inter-like stack — adjust if project prefers a different typeface.
    return const TextTheme().apply(
      bodyColor: scheme.onSurface,
      displayColor: scheme.onSurface,
    );
  }
}
