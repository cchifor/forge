import 'package:dio/dio.dart';
import 'package:{{project_slug}}/src/api/client/auth_interceptor.dart';
import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../helpers/mocks.dart';

const _retriedFlag = '__authInterceptorRetried';

void main() {
  setUpAll(() {
    registerFallbackValue(RequestOptions(path: '/'));
  });

  late MockAuthRepository mockAuthRepo;
  late ProviderContainer container;
  late AuthInterceptor interceptor;
  late MockRequestInterceptorHandler mockRequestHandler;
  late MockErrorInterceptorHandler mockErrorHandler;

  setUp(() {
    mockAuthRepo = MockAuthRepository();
    container = ProviderContainer(
      overrides: [
        authRepositoryProvider.overrideWithValue(mockAuthRepo),
      ],
    );
    // Build the interceptor by capturing the container's Ref via a
    // throwaway provider (same pattern as production wiring).
    late Ref capturedRef;
    final testProvider = Provider<void>((ref) {
      capturedRef = ref;
    });
    container.read(testProvider);
    interceptor = AuthInterceptor(capturedRef);
    mockRequestHandler = MockRequestInterceptorHandler();
    mockErrorHandler = MockErrorInterceptorHandler();
  });

  tearDown(() => container.dispose());

  group('AuthInterceptor.onRequest', () {
    test('adds Authorization header when token is available', () {
      when(() => mockAuthRepo.accessToken).thenReturn('test-token');

      final options = RequestOptions(path: '/test');
      interceptor.onRequest(options, mockRequestHandler);

      expect(options.headers['Authorization'], 'Bearer test-token');
      verify(() => mockRequestHandler.next(options)).called(1);
    });

    test('does not add Authorization header when token is null', () {
      when(() => mockAuthRepo.accessToken).thenReturn(null);

      final options = RequestOptions(path: '/test');
      interceptor.onRequest(options, mockRequestHandler);

      expect(options.headers.containsKey('Authorization'), isFalse);
      verify(() => mockRequestHandler.next(options)).called(1);
    });

    test('always calls handler.next to continue the request', () {
      when(() => mockAuthRepo.accessToken).thenReturn(null);

      final options = RequestOptions(path: '/api/data');
      interceptor.onRequest(options, mockRequestHandler);

      verify(() => mockRequestHandler.next(options)).called(1);
    });

    test('reads token from auth repository on each request', () {
      when(() => mockAuthRepo.accessToken).thenReturn('token-1');

      final options1 = RequestOptions(path: '/first');
      interceptor.onRequest(options1, mockRequestHandler);

      when(() => mockAuthRepo.accessToken).thenReturn('token-2');

      final options2 = RequestOptions(path: '/second');
      interceptor.onRequest(options2, mockRequestHandler);

      expect(options1.headers['Authorization'], 'Bearer token-1');
      expect(options2.headers['Authorization'], 'Bearer token-2');
    });

    test('preserves existing headers when adding Authorization', () {
      when(() => mockAuthRepo.accessToken).thenReturn('test-token');

      final options = RequestOptions(
        path: '/test',
        headers: {'Accept': 'application/json'},
      );
      interceptor.onRequest(options, mockRequestHandler);

      expect(options.headers['Accept'], 'application/json');
      expect(options.headers['Authorization'], 'Bearer test-token');
    });

    test('does not add empty Authorization header when token is null', () {
      when(() => mockAuthRepo.accessToken).thenReturn(null);

      final options = RequestOptions(
        path: '/test',
        headers: {'Accept': 'application/json'},
      );
      interceptor.onRequest(options, mockRequestHandler);

      expect(options.headers.length, 1);
      expect(options.headers['Accept'], 'application/json');
    });
  });

  group('AuthInterceptor.onError (native 401 → refresh → retry)', () {
    late MockDio mockDio;

    DioException buildDioError({
      int statusCode = 401,
      bool retried = false,
    }) {
      final options = RequestOptions(
        path: '/api/protected',
        extra: retried ? {_retriedFlag: true} : <String, dynamic>{},
      );
      return DioException(
        requestOptions: options,
        response: Response<dynamic>(
          requestOptions: options,
          statusCode: statusCode,
        ),
        type: DioExceptionType.badResponse,
      );
    }

    setUp(() {
      mockDio = MockDio();
      interceptor.bindDio(mockDio);
    });

    test('passes non-401 errors straight through to next() — '
        'retry is reserved for token-expiry recovery', () async {
      final err = buildDioError(statusCode: 500);

      await interceptor.onError(err, mockErrorHandler);

      verify(() => mockErrorHandler.next(err)).called(1);
      verifyNever(() => mockAuthRepo.refreshAccessToken());
      verifyNever(() => mockDio.fetch(any()));
    });

    test('passes already-retried 401 through — single-retry guard '
        'prevents recursion when the rotated token is still rejected',
        () async {
      final err = buildDioError(statusCode: 401, retried: true);

      await interceptor.onError(err, mockErrorHandler);

      verify(() => mockErrorHandler.next(err)).called(1);
      verifyNever(() => mockAuthRepo.refreshAccessToken());
      verifyNever(() => mockDio.fetch(any()));
    });

    test('happy path — refreshes the token, replays the request, '
        'and resolves the retried response', () async {
      final err = buildDioError(statusCode: 401);
      final replayedResponse = Response<String>(
        requestOptions: err.requestOptions,
        statusCode: 200,
        data: 'ok',
      );
      when(() => mockAuthRepo.refreshAccessToken())
          .thenAnswer((_) async => DateTime(2030));
      when(() => mockDio.fetch(any()))
          .thenAnswer((_) async => replayedResponse);

      await interceptor.onError(err, mockErrorHandler);

      verify(() => mockAuthRepo.refreshAccessToken()).called(1);
      verify(() => mockDio.fetch(any())).called(1);
      verify(() => mockErrorHandler.resolve(replayedResponse)).called(1);
      verifyNever(() => mockErrorHandler.next(any()));
      // Retry-marker must be set so a second 401 surfaces instead of
      // looping forever.
      expect(err.requestOptions.extra[_retriedFlag], isTrue);
      // Stale Authorization must be cleared so onRequest re-injects
      // the freshly rotated bearer.
      expect(
        err.requestOptions.headers.containsKey('Authorization'),
        isFalse,
      );
    });

    test('refresh failure → logs out and surfaces the original 401 '
        'so the caller can land on /login', () async {
      final err = buildDioError(statusCode: 401);
      when(() => mockAuthRepo.refreshAccessToken())
          .thenThrow(Exception('invalid_grant'));
      when(() => mockAuthRepo.logout()).thenAnswer((_) async {});

      await interceptor.onError(err, mockErrorHandler);

      verify(() => mockAuthRepo.refreshAccessToken()).called(1);
      verify(() => mockAuthRepo.logout()).called(1);
      verify(() => mockErrorHandler.next(err)).called(1);
      verifyNever(() => mockDio.fetch(any()));
      verifyNever(() => mockErrorHandler.resolve(any()));
    });

    test('replay 401 → surfaces the new error to caller', () async {
      final err = buildDioError(statusCode: 401);
      when(() => mockAuthRepo.refreshAccessToken())
          .thenAnswer((_) async => DateTime(2030));
      // The fetch call itself is rejected by the server even with the
      // newly minted bearer (e.g., session-level revocation).
      final replayErr = DioException(
        requestOptions: err.requestOptions,
        response: Response<dynamic>(
          requestOptions: err.requestOptions,
          statusCode: 401,
        ),
        type: DioExceptionType.badResponse,
      );
      when(() => mockDio.fetch(any())).thenThrow(replayErr);

      await interceptor.onError(err, mockErrorHandler);

      verify(() => mockErrorHandler.next(replayErr)).called(1);
      verifyNever(() => mockErrorHandler.resolve(any()));
    });

    test('passes through when Dio is not bound — no replay possible',
        () async {
      // Build a fresh interceptor with no bindDio() call so the retry
      // path can't run. This guards against init-order regressions in
      // dio_client.dart (interceptor must be bound after registration).
      final localContainer = ProviderContainer(
        overrides: [
          authRepositoryProvider.overrideWithValue(mockAuthRepo),
        ],
      );
      addTearDown(localContainer.dispose);
      late Ref capturedRef;
      final refCapture = Provider<void>((ref) {
        capturedRef = ref;
      });
      localContainer.read(refCapture);
      final unboundInterceptor = AuthInterceptor(capturedRef);
      final err = buildDioError(statusCode: 401);

      await unboundInterceptor.onError(err, mockErrorHandler);

      verify(() => mockErrorHandler.next(err)).called(1);
      verifyNever(() => mockAuthRepo.refreshAccessToken());
    });
  });
}
