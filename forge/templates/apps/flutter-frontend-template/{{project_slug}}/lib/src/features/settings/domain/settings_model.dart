import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';
import 'package:freezed_annotation/freezed_annotation.dart';

part 'settings_model.freezed.dart';

/// Accessibility text-size preference applied as a global text scale.
enum TextSize {
  small(0.9375, 'sm'),
  medium(1.0, 'md'),
  large(1.125, 'lg');

  const TextSize(this.scale, this.wire);

  /// Multiplier applied to the app's base font size via [MediaQuery].
  final double scale;

  /// Stable persisted/cross-framework token (`sm` | `md` | `lg`) — matches the
  /// web stores' `text-size` values rather than the Dart enum name.
  final String wire;
}

@freezed
abstract class SettingsState with _$SettingsState {
  const factory SettingsState({
    @Default(ThemeMode.system) ThemeMode themeMode,
    @Default(FlexScheme.blue) FlexScheme flexScheme,
    @Default(TextSize.medium) TextSize textSize,
  }) = _SettingsState;
}
