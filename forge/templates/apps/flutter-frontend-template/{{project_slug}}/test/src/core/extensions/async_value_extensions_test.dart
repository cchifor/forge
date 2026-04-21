import 'package:{{project_slug}}/src/core/errors/app_exception.dart';
import 'package:{{project_slug}}/src/core/extensions/async_value_extensions.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  // isRefreshing now comes from flutter_riverpod's built-in
  // AsyncValueExtensions; removed custom tests to avoid ambiguity.

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
