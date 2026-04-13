import 'package:{{project_slug}}/src/features/auth/domain/token_pair.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('TokenPair', () {
    test('creates with required and optional fields', () {
      final tp = TokenPair(
        accessToken: 'abc',
        refreshToken: 'xyz',
        expiresAt: DateTime(2030),
      );
      expect(tp.accessToken, 'abc');
      expect(tp.refreshToken, 'xyz');
      expect(tp.expiresAt, DateTime(2030));
    });

    test('refreshToken and expiresAt default to null', () {
      const tp = TokenPair(accessToken: 'abc');
      expect(tp.refreshToken, isNull);
      expect(tp.expiresAt, isNull);
    });

    test('isExpired returns true when expiresAt is in the past', () {
      final tp = TokenPair(
        accessToken: 'abc',
        expiresAt: DateTime.now().subtract(const Duration(minutes: 5)),
      );
      expect(tp.isExpired, isTrue);
    });

    test('isExpired returns false when expiresAt is far in the future', () {
      final tp = TokenPair(
        accessToken: 'abc',
        expiresAt: DateTime.now().add(const Duration(hours: 1)),
      );
      expect(tp.isExpired, isFalse);
    });

    test('isExpired returns false when expiresAt is null', () {
      const tp = TokenPair(accessToken: 'abc');
      expect(tp.isExpired, isFalse);
    });
  });
}
