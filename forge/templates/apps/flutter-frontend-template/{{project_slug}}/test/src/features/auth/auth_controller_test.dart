import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:{{project_slug}}/src/features/auth/domain/auth_state.dart';
import 'package:{{project_slug}}/src/features/auth/presentation/auth_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../fixtures/user.dart';
import '../../../helpers/mocks.dart';

void main() {
  late MockAuthRepository mockAuthRepo;
  late ProviderContainer container;

  setUp(() {
    mockAuthRepo = MockAuthRepository();
    container = ProviderContainer(
      overrides: [
        authRepositoryProvider.overrideWithValue(mockAuthRepo),
      ],
    );
  });

  tearDown(() => container.dispose());

  group('AuthController', () {
    test('init returns authenticated when repo has user', () async {
      when(() => mockAuthRepo.init()).thenAnswer(
        (_) async => const AuthState.authenticated(
          user: testUser,
          accessToken: 'test-token',
        ),
      );

      // Trigger the build
      final future = container.read(authControllerProvider.future);
      final result = await future;

      expect(result, isA<Authenticated>());
      expect((result as Authenticated).user.email, 'dev@localhost');
    });

    test('init returns unauthenticated on error', () async {
      when(() => mockAuthRepo.init()).thenThrow(Exception('network error'));

      final result = await container.read(authControllerProvider.future);
      expect(result, isA<Unauthenticated>());
    });

    test('login transitions to authenticated', () async {
      when(() => mockAuthRepo.init()).thenAnswer(
        (_) async => const AuthState.unauthenticated(),
      );
      when(() => mockAuthRepo.login()).thenAnswer(
        (_) async => const AuthState.authenticated(
          user: testUser,
          accessToken: 'test-token',
        ),
      );

      // Wait for initial build
      await container.read(authControllerProvider.future);

      // Login
      await container.read(authControllerProvider.notifier).login();

      final state = container.read(authControllerProvider);
      expect(state.value, isA<Authenticated>());
    });

    test('logout transitions to unauthenticated', () async {
      when(() => mockAuthRepo.init()).thenAnswer(
        (_) async => const AuthState.authenticated(
          user: testUser,
          accessToken: 'test-token',
        ),
      );
      when(() => mockAuthRepo.logout()).thenAnswer((_) async {});

      await container.read(authControllerProvider.future);
      await container.read(authControllerProvider.notifier).logout();

      final state = container.read(authControllerProvider);
      expect(state.value, isA<Unauthenticated>());
    });
  });
}
