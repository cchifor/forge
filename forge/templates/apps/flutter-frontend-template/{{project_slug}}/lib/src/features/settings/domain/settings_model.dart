import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';
import 'package:freezed_annotation/freezed_annotation.dart';

part 'settings_model.freezed.dart';

/// Accessibility text-size preference applied as a global text scale.
enum TextSize {
  small(0.9375),
  medium(1.0),
  large(1.125);

  const TextSize(this.scale);

  /// Multiplier applied to the app's base font size via [MediaQuery].
  final double scale;
}

@freezed
abstract class SettingsState with _$SettingsState {
  const factory SettingsState({
    @Default(ThemeMode.system) ThemeMode themeMode,
    @Default(FlexScheme.blue) FlexScheme flexScheme,
    @Default(TextSize.medium) TextSize textSize,
  }) = _SettingsState;
}
