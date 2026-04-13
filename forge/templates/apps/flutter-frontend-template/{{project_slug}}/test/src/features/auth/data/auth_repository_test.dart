import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:{{project_slug}}/src/features/auth/domain/auth_state.dart';
import 'package:{{project_slug}}/src/features/auth/domain/token_pair.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../../fixtures/user.dart';
import '../../../../helpers/mocks.dart';

void main() {
  late MockDevAuthService mockDevService;
  late MockKeycloakAuthService mockKcService;

  setUp(() {
    mockDevService = MockDevAuthService();
    mockKcService = MockKeycloakAuthService();
  });

  group('AuthRepository (authDisabled=true)', () {
    late AuthRepository repo;

    setUp(() {
      repo = AuthRepository(
        devService: mockDevService,
        authDisabled: true,
      );
    });

    test('init() delegates to DevAuthService and returns authenticated', () async {
      when(() => mockDevService.init()).thenAnswer((_) async => testUser);
      when(() => mockDevService.accessToken).thenReturn('dev-token');

      final state = await repo.init();

      expect(state, isA<Authenticated>());
      expect((state as Authenticated).user.email, 'dev@localhost');
      expect(state.accessToken, 'dev-token');
      verify(() => mockDevService.init()).called(1);
    });

    test('init() returns unauthenticated when dev service returns null', () async {
      when(() => mockDevService.init()).thenAnswer((_) async => null);
      when(() => mockDevService.accessToken).thenReturn(null);

      final state = await repo.init();

      expect(state, isA<Unauthenticated>());
    });

    test('login() delegates to DevAuthService', () async {
      const tokenPair = TokenPair(accessToken: 'dev-token', refreshToken: null);
      when(() => mockDevService.login())
          .thenAnswer((_) async => (testUser, tokenPair));

      final state = await repo.login();

      expect(state, isA<Authenticated>());
      expect((state as Authenticated).user.email, 'dev@localhost');
      expect(repo.accessToken, 'dev-token');
      verify(() => mockDevService.login()).called(1);
    });

    test('logout() delegates to DevAuthService and clears token', () async {
      when(() => mockDevService.logout()).thenAnswer((_) async {});

      await repo.logout();

      expect(repo.accessToken, isNull);
      verify(() => mockDevService.logout()).called(1);
    });

    test('currentUser delegates to DevAuthService', () {
      when(() => mockDevService.currentUser).thenReturn(testUser);

      expect(repo.currentUser, testUser);
      verify(() => mockDevService.currentUser).called(1);
    });
  });

  group('AuthRepository (authDisabled=false)', () {
    late AuthRepository repo;

    setUp(() {
      repo = AuthRepository(
        keycloakService: mockKcService,
        authDisabled: false,
      );
    });

    test('init() delegates to KeycloakAuthService', () async {
      when(() => mockKcService.init()).thenAnswer((_) async => testUser);
      when(() => mockKcService.accessToken).thenReturn('kc-token');

      final state = await repo.init();

      expect(state, isA<Authenticated>());
      expect(repo.accessToken, 'kc-token');
      verify(() => mockKcService.init()).called(1);
    });

    test('login() delegates to KeycloakAuthService', () async {
      const tokenPair = TokenPair(accessToken: 'kc-token', refreshToken: 'refresh');
      when(() => mockKcService.login())
          .thenAnswer((_) async => (testUser, tokenPair));

      final state = await repo.login();

      expect(state, isA<Authenticated>());
      expect(repo.accessToken, 'kc-token');
      verify(() => mockKcService.login()).called(1);
    });

    test('logout() delegates to KeycloakAuthService', () async {
      when(() => mockKcService.logout()).thenAnswer((_) async {});

      await repo.logout();

      expect(repo.accessToken, isNull);
      verify(() => mockKcService.logout()).called(1);
    });
  });
}
