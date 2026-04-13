import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';
import 'package:{{project_slug}}/src/features/settings/domain/settings_model.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('SettingsState', () {
    test('defaults to system theme mode and blue scheme', () {
      const state = SettingsState();
      expect(state.themeMode, ThemeMode.system);
      expect(state.flexScheme, FlexScheme.blue);
    });

    test('copyWith changes themeMode', () {
      const state = SettingsState();
      final updated = state.copyWith(themeMode: ThemeMode.dark);
      expect(updated.themeMode, ThemeMode.dark);
      expect(updated.flexScheme, FlexScheme.blue);
    });

    test('copyWith changes flexScheme', () {
      const state = SettingsState();
      final updated = state.copyWith(flexScheme: FlexScheme.green);
      expect(updated.flexScheme, FlexScheme.green);
      expect(updated.themeMode, ThemeMode.system);
    });

    test('two instances with same values are equal', () {
      const a = SettingsState();
      const b = SettingsState();
      expect(a, equals(b));
    });

    test('instances with different values are not equal', () {
      const a = SettingsState();
      const b = SettingsState(themeMode: ThemeMode.dark);
      expect(a, isNot(equals(b)));
    });
  });
}
