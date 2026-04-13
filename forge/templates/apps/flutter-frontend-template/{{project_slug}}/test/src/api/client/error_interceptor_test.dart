import 'package:dio/dio.dart';
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

  DioException _createDioException({
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
        final err = _createDioException(statusCode: 401);

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
        final err = _createDioException(statusCode: 403);

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
        final err = _createDioException(statusCode: 404);

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
        final err = _createDioException(statusCode: 409);

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
        final err = _createDioException(statusCode: 422);

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
        final err = _createDioException(statusCode: 500);

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
        final err = _createDioException(
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
        final err = _createDioException(
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
        final err = _createDioException(
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
  });
}
