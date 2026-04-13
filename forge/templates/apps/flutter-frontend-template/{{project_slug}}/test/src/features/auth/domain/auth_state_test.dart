import 'package:{{project_slug}}/src/features/auth/domain/auth_state.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../../../fixtures/user.dart';

void main() {
  group('AuthState', () {
    test('Authenticated contains user and accessToken', () {
      const state = AuthState.authenticated(
        user: testUser,
        accessToken: 'tok-123',
      );
      expect(state, isA<Authenticated>());
      final auth = state as Authenticated;
      expect(auth.user, testUser);
      expect(auth.accessToken, 'tok-123');
    });

    test('Unauthenticated creates successfully', () {
      const state = AuthState.unauthenticated();
      expect(state, isA<Unauthenticated>());
    });

    test('pattern matching with switch works', () {
      const AuthState state = AuthState.authenticated(
        user: testUser,
        accessToken: 'tok',
      );

      final result = switch (state) {
        Authenticated(:final user) => 'Hello ${user.username}',
        Unauthenticated() => 'Not logged in',
      };

      expect(result, 'Hello dev-user');
    });

    test('pattern matching Unauthenticated branch', () {
      const AuthState state = AuthState.unauthenticated();

      final result = switch (state) {
        Authenticated() => 'logged in',
        Unauthenticated() => 'not logged in',
      };

      expect(result, 'not logged in');
    });
  });
}
