import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/storage/key_value_storage.dart';

part 'theme_provider.g.dart';

const _themeModeKey = 'theme_mode';
const _flexSchemeKey = 'flex_scheme';
const _darkModeVariantKey = 'dark_mode_variant';

enum DarkModeVariant { standard, oled }

@Riverpod(keepAlive: true)
class ThemeModeNotifier extends _$ThemeModeNotifier {
  SharedPreferences get _prefs => ref.read(keyValueStorageProvider);

  @override
  ThemeMode build() {
    final stored = _prefs.getString(_themeModeKey);
    return switch (stored) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    state = mode;
    await _prefs.setString(_themeModeKey, mode.name);
  }
}

@Riverpod(keepAlive: true)
class FlexSchemeNotifier extends _$FlexSchemeNotifier {
  SharedPreferences get _prefs => ref.read(keyValueStorageProvider);

  @override
  FlexScheme build() {
    final stored = _prefs.getString(_flexSchemeKey);
    if (stored != null) {
      return FlexScheme.values.firstWhere(
        (s) => s.name == stored,
        orElse: () => FlexScheme.blue,
      );
    }
    return FlexScheme.blue;
  }

  Future<void> setScheme(FlexScheme scheme) async {
    state = scheme;
    await _prefs.setString(_flexSchemeKey, scheme.name);
  }
}

@Riverpod(keepAlive: true)
class DarkModeVariantNotifier extends _$DarkModeVariantNotifier {
  SharedPreferences get _prefs => ref.read(keyValueStorageProvider);

  @override
  DarkModeVariant build() {
    final stored = _prefs.getString(_darkModeVariantKey);
    return stored == 'oled' ? DarkModeVariant.oled : DarkModeVariant.standard;
  }

  Future<void> setVariant(DarkModeVariant variant) async {
    state = variant;
    await _prefs.setString(_darkModeVariantKey, variant.name);
  }
}
