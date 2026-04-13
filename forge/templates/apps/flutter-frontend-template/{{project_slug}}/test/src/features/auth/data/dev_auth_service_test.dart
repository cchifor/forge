import 'package:{{project_slug}}/src/features/auth/data/dev_auth_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late DevAuthService service;

  setUp(() {
    service = DevAuthService();
  });

  group('DevAuthService', () {
    test('init() returns the dev user', () async {
      final user = await service.init();

      expect(user, isNotNull);
      expect(user!.email, 'dev@localhost');
      expect(user.username, 'dev-user');
      expect(user.firstName, 'Dev');
      expect(user.lastName, 'User');
      expect(user.roles, contains('admin'));
    });

    test('login() returns dev user and token pair', () async {
      final (user, tokenPair) = await service.login();

      expect(user.email, 'dev@localhost');
      expect(user.username, 'dev-user');
      expect(tokenPair.accessToken, 'dev-token');
      expect(tokenPair.refreshToken, isNull);
      expect(tokenPair.expiresAt, isNull);
    });

    test('logout() completes without error', () async {
      await expectLater(service.logout(), completes);
    });

    test('accessToken returns dev-token', () {
      expect(service.accessToken, 'dev-token');
    });

    test('currentUser returns the dev user', () {
      final user = service.currentUser;

      expect(user, isNotNull);
      expect(user!.id, '00000000-0000-0000-0000-000000000001');
      expect(user.email, 'dev@localhost');
    });

    test('login() returns consistent user and token', () async {
      final (user1, _) = await service.login();
      final (user2, _) = await service.login();

      expect(user1.id, user2.id);
      expect(user1.email, user2.email);
    });
  });
}
