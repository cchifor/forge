import 'package:{{project_slug}}/src/theme/design_tokens.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('DesignTokens spacing', () {
    test('all spacing values are positive', () {
      const spacings = [
        DesignTokens.p4,
        DesignTokens.p8,
        DesignTokens.p12,
        DesignTokens.p16,
        DesignTokens.p20,
        DesignTokens.p24,
        DesignTokens.p32,
        DesignTokens.p48,
        DesignTokens.p64,
      ];
      for (final s in spacings) {
        expect(s, greaterThan(0), reason: 'spacing $s should be positive');
      }
    });

    test('spacing scale increases monotonically', () {
      const spacings = [
        DesignTokens.p4,
        DesignTokens.p8,
        DesignTokens.p12,
        DesignTokens.p16,
        DesignTokens.p20,
        DesignTokens.p24,
        DesignTokens.p32,
        DesignTokens.p48,
        DesignTokens.p64,
      ];
      for (var i = 1; i < spacings.length; i++) {
        expect(
          spacings[i],
          greaterThan(spacings[i - 1]),
          reason: 'spacing[${i}] should be > spacing[${i - 1}]',
        );
      }
    });
  });

  group('DesignTokens border radius', () {
    test('all radius values are positive', () {
      expect(DesignTokens.radiusSmall, greaterThan(0));
      expect(DesignTokens.radiusMedium, greaterThan(0));
      expect(DesignTokens.radiusLarge, greaterThan(0));
      expect(DesignTokens.radiusXLarge, greaterThan(0));
    });

    test('radius scale increases monotonically', () {
      const radii = [
        DesignTokens.radiusSmall,
        DesignTokens.radiusMedium,
        DesignTokens.radiusLarge,
        DesignTokens.radiusXLarge,
      ];
      for (var i = 1; i < radii.length; i++) {
        expect(
          radii[i],
          greaterThan(radii[i - 1]),
          reason: 'radius[${i}] should be > radius[${i - 1}]',
        );
      }
    });
  });

  group('DesignTokens breakpoints', () {
    test('compact is less than or equal to medium', () {
      expect(DesignTokens.compactWidth, lessThanOrEqualTo(DesignTokens.mediumWidth));
    });
  });

  group('DesignTokens icon sizes', () {
    test('icon sizes increase from XS to Hero', () {
      const icons = [
        DesignTokens.iconXS,
        DesignTokens.iconSM,
        DesignTokens.iconMD,
        DesignTokens.iconLG,
        DesignTokens.iconXL,
        DesignTokens.iconHero,
      ];
      for (var i = 1; i < icons.length; i++) {
        expect(
          icons[i],
          greaterThan(icons[i - 1]),
          reason: 'icon[${i}] should be > icon[${i - 1}]',
        );
      }
    });
  });

  group('DesignTokens sidebar', () {
    test('collapsed width is less than expanded width', () {
      expect(
        DesignTokens.sidebarCollapsedWidth,
        lessThan(DesignTokens.sidebarExpandedWidth),
      );
    });

    test('icon column width equals collapsed minus 2x body padding', () {
      expect(
        DesignTokens.sidebarIconColumnWidth,
        DesignTokens.sidebarCollapsedWidth - DesignTokens.sidebarBodyPadding * 2,
      );
    });
  });
}
