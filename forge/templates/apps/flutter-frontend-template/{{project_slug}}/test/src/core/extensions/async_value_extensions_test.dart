import 'package:{{project_slug}}/src/core/errors/app_exception.dart';
import 'package:{{project_slug}}/src/core/extensions/async_value_extensions.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('isRefreshing', () {
    test('returns false for pure AsyncLoading (no previous value)', () {
      const value = AsyncLoading<int>();
      expect(value.isRefreshing, isFalse);
    });

    test('returns true for AsyncData that is loading (refresh)', () {
      const original = AsyncData<int>(42);
      final refreshing = original.copyWithPrevious(const AsyncLoading());
      expect(refreshing.isRefreshing, isTrue);
    });

    test('returns false for AsyncData that is not loading', () {
      const value = AsyncData<int>(42);
      expect(value.isRefreshing, isFalse);
    });

    test('returns false for AsyncError that is not loading', () {
      final value = AsyncError<int>(Exception('fail'), StackTrace.current);
      expect(value.isRefreshing, isFalse);
    });
  });

  group('appException', () {
    test('returns AppException from AsyncError', () {
      const appError = NetworkException(message: 'Offline');
      final value = AsyncError<int>(appError, StackTrace.current);
      expect(value.appException, isA<NetworkException>());
      expect(value.appException?.message, 'Offline');
    });

    test('returns null when AsyncError contains non-AppException', () {
      final value = AsyncError<int>(Exception('generic'), StackTrace.current);
      expect(value.appException, isNull);
    });

    test('returns null for AsyncData', () {
      const value = AsyncData<int>(42);
      expect(value.appException, isNull);
    });

    test('returns null for AsyncLoading', () {
      const value = AsyncLoading<int>();
      expect(value.appException, isNull);
    });
  });
}
