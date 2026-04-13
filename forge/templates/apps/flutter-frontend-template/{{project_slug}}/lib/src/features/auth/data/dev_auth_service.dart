import '../domain/token_pair.dart';
import '../domain/user_model.dart';

class DevAuthService {
  static const _devUser = User(
    id: '00000000-0000-0000-0000-000000000001',
    email: 'dev@localhost',
    username: 'dev-user',
    firstName: 'Dev',
    lastName: 'User',
    roles: ['admin', 'user'],
    customerId: '00000000-0000-0000-0000-000000000001',
    orgId: null,
  );

  static const _devToken = TokenPair(
    accessToken: 'dev-token',
    refreshToken: null,
    expiresAt: null,
  );

  Future<User?> init() async => _devUser;

  Future<(User, TokenPair)> login() async => (_devUser, _devToken);

  Future<void> logout() async {}

  String? get accessToken => 'dev-token';

  User? get currentUser => _devUser;
}
