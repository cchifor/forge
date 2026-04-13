import 'package:{{project_slug}}/src/core/errors/app_exception.dart';
import 'package:{{project_slug}}/src/core/errors/error_formatters.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('ServerException', () {
    test('stores statusCode and message', () {
      const e = ServerException(statusCode: 500, message: 'Internal error');
      expect(e.statusCode, 500);
      expect(e.message, 'Internal error');
      expect(e.type, isNull);
      expect(e.detail, isNull);
    });

    test('stores optional type and detail', () {
      const e = ServerException(
        statusCode: 422,
        message: 'Validation failed',
        type: 'validation_error',
        detail: {'field': 'name'},
      );
      expect(e.type, 'validation_error');
      expect(e.detail, {'field': 'name'});
    });
  });

  group('NetworkException', () {
    test('stores message', () {
      const e = NetworkException(message: 'No connection');
      expect(e.message, 'No connection');
    });
  });

  group('UnauthorizedException', () {
    test('has default message', () {
      const e = UnauthorizedException();
      expect(e.message, 'Authentication required');
    });

    test('accepts custom message', () {
      const e = UnauthorizedException(message: 'Token expired');
      expect(e.message, 'Token expired');
    });
  });

  group('NotFoundException', () {
    test('stores message', () {
      const e = NotFoundException(message: 'Item not found');
      expect(e.message, 'Item not found');
    });
  });

  group('ConflictException', () {
    test('stores message', () {
      const e = ConflictException(message: 'Already exists');
      expect(e.message, 'Already exists');
    });
  });

  group('ValidationException', () {
    test('stores message and optional errors list', () {
      const e = ValidationException(
        message: 'Invalid input',
        errors: ['Name is required', 'Email is invalid'],
      );
      expect(e.message, 'Invalid input');
      expect(e.errors, hasLength(2));
    });

    test('errors defaults to null', () {
      const e = ValidationException(message: 'Bad request');
      expect(e.errors, isNull);
    });
  });

  group('formatAppException', () {
    test('formats ServerException with status code', () {
      const e = ServerException(statusCode: 503, message: 'Unavailable');
      expect(formatAppException(e), 'Server error (503): Unavailable');
    });

    test('formats NetworkException', () {
      const e = NetworkException(message: 'Timeout');
      expect(formatAppException(e), 'Network error: Timeout');
    });

    test('formats UnauthorizedException with fixed text', () {
      const e = UnauthorizedException();
      expect(formatAppException(e), 'Please sign in to continue.');
    });

    test('formats NotFoundException with its message', () {
      const e = NotFoundException(message: 'User not found');
      expect(formatAppException(e), 'User not found');
    });

    test('formats ConflictException with its message', () {
      const e = ConflictException(message: 'Duplicate entry');
      expect(formatAppException(e), 'Duplicate entry');
    });

    test('formats ValidationException with errors list when present', () {
      const e = ValidationException(
        message: 'Validation failed',
        errors: ['Field A required', 'Field B too long'],
      );
      expect(
        formatAppException(e),
        'Field A required\nField B too long',
      );
    });

    test('formats ValidationException with message when errors empty', () {
      const e = ValidationException(message: 'Validation failed', errors: []);
      expect(formatAppException(e), 'Validation failed');
    });

    test('formats ValidationException with message when errors null', () {
      const e = ValidationException(message: 'Validation failed');
      expect(formatAppException(e), 'Validation failed');
    });
  });

  group('formatException', () {
    test('delegates to formatAppException for AppException', () {
      const e = NetworkException(message: 'Offline');
      expect(formatException(e), 'Network error: Offline');
    });

    test('returns generic message for non-AppException', () {
      expect(
        formatException(Exception('random')),
        'An unexpected error occurred.',
      );
    });
  });
}
