import 'package:{{project_slug}}/src/features/auth/domain/user_model.dart';

const testUser = User(
  id: '00000000-0000-0000-0000-000000000001',
  email: 'dev@localhost',
  username: 'dev-user',
  firstName: 'Dev',
  lastName: 'User',
  roles: ['admin', 'user'],
  customerId: '00000000-0000-0000-0000-000000000001',
  orgId: null,
);

const testUserJson = {
  'sub': '00000000-0000-0000-0000-000000000001',
  'email': 'dev@localhost',
  'preferred_username': 'dev-user',
  'given_name': 'Dev',
  'family_name': 'User',
  'realm_access': {
    'roles': ['admin', 'user'],
  },
  'customer_id': '00000000-0000-0000-0000-000000000001',
};
