import 'package:dio/dio.dart';
import 'package:{{project_slug}}/src/api/client/app_exception.dart' as api;
import 'package:{{project_slug}}/src/api/client/error_interceptor.dart';
import 'package:{{project_slug}}/src/core/errors/app_exception.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../helpers/mocks.dart';

void main() {
  late ErrorInterceptor interceptor;
  late MockErrorInterceptorHandler mockHandler;

  setUp(() {
    interceptor = ErrorInterceptor();
    mockHandler = MockErrorInterceptorHandler();
  });

  DioException createDioException({
    int? statusCode,
    dynamic data,
    DioExceptionType type = DioExceptionType.badResponse,
  }) {
    final requestOptions = RequestOptions(path: '/test');
    return DioException(
      requestOptions: requestOptions,
      type: type,
      response: statusCode != null
          ? Response(
              requestOptions: requestOptions,
              statusCode: statusCode,
              data: data,
            )
          : null,
    );
  }

  group('ErrorInterceptor', () {
    group('HTTP status code mapping', () {
      test('maps 401 to UnauthorizedException', () {
        final err = createDioException(statusCode: 401);

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<UnauthorizedException>());
        expect(
          (captured.error as UnauthorizedException).message,
          'Authentication required',
        );
      });

      test('maps 403 to UnauthorizedException with access denied', () {
        final err = createDioException(statusCode: 403);

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<UnauthorizedException>());
        expect(
          (captured.error as UnauthorizedException).message,
          'Access denied',
        );
      });

      test('maps 404 to NotFoundException', () {
        final err = createDioException(statusCode: 404);

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<NotFoundException>());
        expect(
          (captured.error as NotFoundException).message,
          'Resource not found',
        );
      });

      test('maps 409 to ConflictException', () {
        final err = createDioException(statusCode: 409);

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<ConflictException>());
        expect(
          (captured.error as ConflictException).message,
          'Resource conflict',
        );
      });

      test('maps 422 to ValidationException', () {
        final err = createDioException(statusCode: 422);

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<ValidationException>());
        expect(
          (captured.error as ValidationException).message,
          'Validation failed',
        );
      });

      test('maps 500 to ServerException', () {
        final err = createDioException(statusCode: 500);

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<ServerException>());
        expect(
          (captured.error as ServerException).statusCode,
          500,
        );
      });
    });

    group('network errors', () {
      test('maps connectionTimeout to NetworkException', () {
        final err = createDioException(
          type: DioExceptionType.connectionTimeout,
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<NetworkException>());
        expect(
          (captured.error as NetworkException).message,
          'Connection timed out',
        );
      });

      test('maps connectionError to NetworkException', () {
        final err = createDioException(
          type: DioExceptionType.connectionError,
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<NetworkException>());
        expect(
          (captured.error as NetworkException).message,
          'Unable to connect. Check your network.',
        );
      });

      test('maps null response to NetworkException', () {
        final err = DioException(
          requestOptions: RequestOptions(path: '/test'),
          type: DioExceptionType.unknown,
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<NetworkException>());
        expect(
          (captured.error as NetworkException).message,
          'No response from server',
        );
      });
    });

    group('API error parsing', () {
      test('uses message from API error response body', () {
        final err = createDioException(
          statusCode: 404,
          data: <String, dynamic>{
            'message': 'User not found',
            'type': 'not_found',
          },
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<NotFoundException>());
        expect(
          (captured.error as NotFoundException).message,
          'User not found',
        );
      });
    });

    // RFC-011 acceptance (1.2.0) — Gap 1: parse the RFC-007 error
    // envelope into a typed ``api.AppException`` (carrying ``code``,
    // ``type``, ``context``, ``correlationId``) instead of collapsing
    // to ``DioException.message``. Falls back to the legacy
    // ``AppException`` family whenever the body does not match.
    group('RFC-007 envelope parsing', () {
      test('parses envelope body into typed api.AppException', () {
        final err = createDioException(
          statusCode: 404,
          data: <String, dynamic>{
            'error': <String, dynamic>{
              'code': 'NOT_FOUND',
              'message': "Item 'abc-123' not found",
              'type': 'NotFoundError',
              'context': <String, dynamic>{'item_id': 'abc-123'},
              'correlation_id': '01H-correlation-id',
            },
          },
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<api.AppException>());
        final exception = captured.error as api.AppException;
        expect(exception.code, 'NOT_FOUND');
        expect(exception.message, "Item 'abc-123' not found");
        expect(exception.type, 'NotFoundError');
        expect(exception.context['item_id'], 'abc-123');
        expect(exception.correlationId, '01H-correlation-id');
        expect(exception.statusCode, 404);
      });

      test('falls back to legacy AppException on non-envelope body', () {
        // Body lacks the top-level ``error`` wrapper; this is the
        // pre-1.2.0 shape and must keep flowing through the existing
        // status-code switch (this asserts the fallback path stays
        // intact for any backend that has not yet adopted RFC-007).
        final err = createDioException(
          statusCode: 409,
          data: <String, dynamic>{
            'message': 'Item already exists',
            'type': 'conflict',
          },
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<ConflictException>());
        expect(captured.error, isNot(isA<api.AppException>()));
        expect(
          (captured.error as ConflictException).message,
          'Item already exists',
        );
      });

      test(
          'falls back to legacy NetworkException when no response body is '
          'present', () {
        // Network-level failure (no response) — the envelope-parsing
        // branch never runs because the early ``response == null``
        // guard short-circuits to NetworkException. Locks in that
        // ordering so a future refactor cannot accidentally reorder
        // the envelope check ahead of the network-level guard and
        // start raising spurious AppException(code: '') on socket
        // failures.
        final err = DioException(
          requestOptions: RequestOptions(path: '/test'),
          type: DioExceptionType.unknown,
        );

        interceptor.onError(err, mockHandler);

        final captured =
            verify(() => mockHandler.reject(captureAny())).captured.single
                as DioException;
        expect(captured.error, isA<NetworkException>());
        expect(captured.error, isNot(isA<api.AppException>()));
        expect(
          (captured.error as NetworkException).message,
          'No response from server',
        );
      });
    });
  });
}
