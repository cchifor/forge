import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'ai_theme_extension.dart';
import 'layout_theme_extension.dart';

// ── Sub-theme defaults ──

const _subThemes = FlexSubThemesData(
  interactionEffects: true,
  useM2StyleDividerInM3: true,
  inputDecoratorBorderType: FlexInputBorderType.outline,
  inputDecoratorRadius: 12,
  chipRadius: 8,
  fabRadius: 16,
  cardRadius: 12,
  dialogRadius: 16,
  navigationBarIndicatorOpacity: 1.0,
  navigationRailIndicatorOpacity: 1.0,
  // Disable all surface blending -- VS Code uses flat colors
  blendOnLevel: 0,
  blendOnColors: false,
);

String? get _fontFamily => GoogleFonts.inter().fontFamily;

// ── VS Code FlexSchemeColor palettes (accent colors + error) ──

const _vsCodeDefault = Color(0xFF007ACC);

const _vsCodeLightPalette = FlexSchemeColor(
  primary: _vsCodeDefault,
  primaryContainer: Color(0xFFD4EAF9),
  secondary: _vsCodeDefault,
  secondaryContainer: Color(0xFFD4EAF9),
  appBarColor: Color(0xFF2C2C2C),
  error: Color(0xFFE51400),
);

const _vsCodeDarkPalette = FlexSchemeColor(
  primary: _vsCodeDefault,
  primaryContainer: Color(0xFF0E639C),
  secondary: _vsCodeDefault,
  secondaryContainer: Color(0xFF0E639C),
  appBarColor: Color(0xFF333333),
  error: Color(0xFFF48771),
);

// ── VS Code surface color palettes (flat, no primary tint) ──

const _vsLight = _VsCodeSurfaces(
  scaffold: Color(0xFFFFFFFF),
  surface: Color(0xFFFFFFFF),
  surfaceContainer: Color(0xFFF3F3F3),
  surfaceContainerLow: Color(0xFFF8F8F8),
  surfaceContainerHigh: Color(0xFFEBEBEB),
  outline: Color(0xFFD4D4D4),
);

const _vsDark = _VsCodeSurfaces(
  scaffold: Color(0xFF1E1E1E),
  surface: Color(0xFF1E1E1E),
  surfaceContainer: Color(0xFF252526),
  surfaceContainerLow: Color(0xFF252526),
  surfaceContainerHigh: Color(0xFF2D2D2D),
  outline: Color(0xFF3C3C3C),
);

const _vsOled = _VsCodeSurfaces(
  scaffold: Color(0xFF000000),
  surface: Color(0xFF000000),
  surfaceContainer: Color(0xFF0A0A0A),
  surfaceContainerLow: Color(0xFF0A0A0A),
  surfaceContainerHigh: Color(0xFF141414),
  outline: Color(0xFF2A2A2A),
);

// ── Theme builders ──

/// Override the VS Code palette's accent with the user-selected [FlexScheme].
FlexSchemeColor _withAccent(
  FlexSchemeColor base,
  FlexScheme scheme,
  Brightness brightness,
) {
  final schemeColors = FlexColor.schemes[scheme];
  final accent = brightness == Brightness.light
      ? schemeColors?.light.primary
      : schemeColors?.dark.primary;
  if (accent == null || accent == base.primary) return base;
  return base.copyWith(primary: accent, secondary: accent);
}

ThemeData lightTheme(FlexScheme scheme) {
  final colors = _withAccent(_vsCodeLightPalette, scheme, Brightness.light);
  final base = FlexThemeData.light(
    colors: colors,
    useMaterial3: true,
    fontFamily: _fontFamily,
    surfaceMode: FlexSurfaceMode.level,
    blendLevel: 0,
    subThemesData: _subThemes,
  );
  return _applyVsSurfaces(base, _vsLight, [
    AiThemeColors.light,
    LayoutThemeExtension.standard,
  ]);
}

ThemeData darkTheme(FlexScheme scheme) {
  final colors = _withAccent(_vsCodeDarkPalette, scheme, Brightness.dark);
  final base = FlexThemeData.dark(
    colors: colors,
    useMaterial3: true,
    fontFamily: _fontFamily,
    surfaceMode: FlexSurfaceMode.level,
    blendLevel: 0,
    subThemesData: _subThemes,
  );
  return _applyVsSurfaces(base, _vsDark, [
    AiThemeColors.dark,
    LayoutThemeExtension.standard,
  ]);
}

ThemeData oledDarkTheme(FlexScheme scheme) {
  final colors = _withAccent(_vsCodeDarkPalette, scheme, Brightness.dark);
  final base = FlexThemeData.dark(
    colors: colors,
    useMaterial3: true,
    darkIsTrueBlack: true,
    fontFamily: _fontFamily,
    surfaceMode: FlexSurfaceMode.level,
    blendLevel: 0,
    subThemesData: _subThemes,
  );
  return _applyVsSurfaces(base, _vsOled, [
    AiThemeColors.oled,
    LayoutThemeExtension.standard,
  ]);
}

// ── Helpers ──

/// Apply VS Code surface colors so all Material widgets inherit correctly.
ThemeData _applyVsSurfaces(
  ThemeData base,
  _VsCodeSurfaces vs,
  List<ThemeExtension> extensions,
) {
  return base.copyWith(
    scaffoldBackgroundColor: vs.scaffold,
    canvasColor: vs.scaffold,
    cardColor: vs.surfaceContainer,
    dialogTheme: DialogThemeData(backgroundColor: vs.surfaceContainerHigh),
    appBarTheme: base.appBarTheme.copyWith(
      backgroundColor: vs.scaffold,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
    ),
    colorScheme: base.colorScheme.copyWith(
      surface: vs.surface,
      surfaceContainerLowest: vs.scaffold,
      surfaceContainerLow: vs.surfaceContainerLow,
      surfaceContainer: vs.surfaceContainer,
      surfaceContainerHigh: vs.surfaceContainerHigh,
      outlineVariant: vs.outline,
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: vs.surfaceContainer,
    ),
    snackBarTheme: const SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
    ),
    extensions: extensions,
  );
}

class _VsCodeSurfaces {
  const _VsCodeSurfaces({
    required this.scaffold,
    required this.surface,
    required this.surfaceContainer,
    required this.surfaceContainerLow,
    required this.surfaceContainerHigh,
    required this.outline,
  });

  final Color scaffold;
  final Color surface;
  final Color surfaceContainer;
  final Color surfaceContainerLow;
  final Color surfaceContainerHigh;
  final Color outline;
}
