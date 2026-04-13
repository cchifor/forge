import 'package:dio/dio.dart';
import 'package:{{project_slug}}/src/api/client/auth_interceptor.dart';
import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../helpers/mocks.dart';

void main() {
  late MockAuthRepository mockAuthRepo;
  late ProviderContainer container;
  late AuthInterceptor interceptor;
  late MockRequestInterceptorHandler mockHandler;

  setUp(() {
    mockAuthRepo = MockAuthRepository();
    container = ProviderContainer(
      overrides: [
        authRepositoryProvider.overrideWithValue(mockAuthRepo),
      ],
    );
    // Create the interceptor using the Dio provider's ref.
    // We build it by reading through the container and injecting the ref
    // via a temporary provider.
    late Ref capturedRef;
    final testProvider = Provider<void>((ref) {
      capturedRef = ref;
    });
    container.read(testProvider);
    interceptor = AuthInterceptor(capturedRef);
    mockHandler = MockRequestInterceptorHandler();
  });

  tearDown(() => container.dispose());

  group('AuthInterceptor', () {
    test('adds Authorization header when token is available', () {
      when(() => mockAuthRepo.accessToken).thenReturn('test-token');

      final options = RequestOptions(path: '/test');
      interceptor.onRequest(options, mockHandler);

      expect(options.headers['Authorization'], 'Bearer test-token');
      verify(() => mockHandler.next(options)).called(1);
    });

    test('does not add Authorization header when token is null', () {
      when(() => mockAuthRepo.accessToken).thenReturn(null);

      final options = RequestOptions(path: '/test');
      interceptor.onRequest(options, mockHandler);

      expect(options.headers.containsKey('Authorization'), isFalse);
      verify(() => mockHandler.next(options)).called(1);
    });

    test('always calls handler.next to continue the request', () {
      when(() => mockAuthRepo.accessToken).thenReturn(null);

      final options = RequestOptions(path: '/api/data');
      interceptor.onRequest(options, mockHandler);

      verify(() => mockHandler.next(options)).called(1);
    });

    test('reads token from auth repository on each request', () {
      when(() => mockAuthRepo.accessToken).thenReturn('token-1');

      final options1 = RequestOptions(path: '/first');
      interceptor.onRequest(options1, mockHandler);

      when(() => mockAuthRepo.accessToken).thenReturn('token-2');

      final options2 = RequestOptions(path: '/second');
      interceptor.onRequest(options2, mockHandler);

      expect(options1.headers['Authorization'], 'Bearer token-1');
      expect(options2.headers['Authorization'], 'Bearer token-2');
    });

    test('preserves existing headers when adding Authorization', () {
      when(() => mockAuthRepo.accessToken).thenReturn('test-token');

      final options = RequestOptions(
        path: '/test',
        headers: {'Accept': 'application/json'},
      );
      interceptor.onRequest(options, mockHandler);

      expect(options.headers['Accept'], 'application/json');
      expect(options.headers['Authorization'], 'Bearer test-token');
    });

    test('does not add empty Authorization header when token is null', () {
      when(() => mockAuthRepo.accessToken).thenReturn(null);

      final options = RequestOptions(
        path: '/test',
        headers: {'Accept': 'application/json'},
      );
      interceptor.onRequest(options, mockHandler);

      expect(options.headers.length, 1);
      expect(options.headers['Accept'], 'application/json');
    });
  });
}
