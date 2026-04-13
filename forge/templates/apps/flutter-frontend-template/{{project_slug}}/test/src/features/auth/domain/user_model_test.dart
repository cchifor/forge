import 'package:{{project_slug}}/src/features/auth/domain/user_model.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../../../fixtures/user.dart';

void main() {
  group('User creation', () {
    test('creates user with required fields', () {
      expect(testUser.id, '00000000-0000-0000-0000-000000000001');
      expect(testUser.email, 'dev@localhost');
      expect(testUser.username, 'dev-user');
      expect(testUser.firstName, 'Dev');
      expect(testUser.lastName, 'User');
      expect(testUser.customerId, '00000000-0000-0000-0000-000000000001');
    });

    test('roles defaults to empty list', () {
      const user = User(
        id: 'u1',
        username: 'test',
        email: 'test@test.com',
        firstName: 'Test',
        lastName: 'User',
        customerId: 'c1',
      );
      expect(user.roles, isEmpty);
    });

    test('orgId defaults to null', () {
      const user = User(
        id: 'u1',
        username: 'test',
        email: 'test@test.com',
        firstName: 'Test',
        lastName: 'User',
        customerId: 'c1',
      );
      expect(user.orgId, isNull);
    });
  });

  group('User.fromJwtClaims', () {
    test('parses all fields from valid claims', () {
      final user = User.fromJwtClaims(testUserJson);
      expect(user.id, '00000000-0000-0000-0000-000000000001');
      expect(user.email, 'dev@localhost');
      expect(user.username, 'dev-user');
      expect(user.firstName, 'Dev');
      expect(user.lastName, 'User');
      expect(user.roles, ['admin', 'user']);
      expect(user.customerId, '00000000-0000-0000-0000-000000000001');
    });

    test('defaults to empty strings when claims are missing', () {
      final user = User.fromJwtClaims(const <String, dynamic>{});
      expect(user.id, '');
      expect(user.username, '');
      expect(user.email, '');
      expect(user.firstName, '');
      expect(user.lastName, '');
      expect(user.roles, isEmpty);
    });

    test('falls back to sub for customerId when customer_id missing', () {
      final user = User.fromJwtClaims(const {'sub': 'sub-id'});
      expect(user.customerId, 'sub-id');
    });
  });

  group('fullName', () {
    test('concatenates firstName and lastName', () {
      expect(testUser.fullName, 'Dev User');
    });

    test('trims when lastName is empty', () {
      const user = User(
        id: 'u1',
        username: 'test',
        email: 'test@test.com',
        firstName: 'Solo',
        lastName: '',
        customerId: 'c1',
      );
      expect(user.fullName, 'Solo');
    });
  });

  group('hasRole and isAdmin', () {
    test('hasRole returns true for existing role', () {
      expect(testUser.hasRole('admin'), isTrue);
      expect(testUser.hasRole('user'), isTrue);
    });

    test('hasRole returns false for missing role', () {
      expect(testUser.hasRole('superadmin'), isFalse);
    });

    test('isAdmin is true when roles contain admin', () {
      expect(testUser.isAdmin, isTrue);
    });

    test('isAdmin is false when roles lack admin', () {
      const user = User(
        id: 'u1',
        username: 'test',
        email: 'test@test.com',
        firstName: 'Test',
        lastName: 'User',
        roles: ['user'],
        customerId: 'c1',
      );
      expect(user.isAdmin, isFalse);
    });
  });

  group('equality and copyWith', () {
    test('two users with same fields are equal', () {
      const a = User(
        id: 'u1',
        username: 'test',
        email: 'test@test.com',
        firstName: 'A',
        lastName: 'B',
        customerId: 'c1',
      );
      const b = User(
        id: 'u1',
        username: 'test',
        email: 'test@test.com',
        firstName: 'A',
        lastName: 'B',
        customerId: 'c1',
      );
      expect(a, equals(b));
    });

    test('copyWith changes specified fields', () {
      final updated = testUser.copyWith(email: 'new@test.com');
      expect(updated.email, 'new@test.com');
      expect(updated.username, testUser.username);
    });
  });
}
