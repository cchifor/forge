import 'package:go_router/go_router.dart';

import '../../routing/route_names.dart';
import 'presentation/login_page.dart';

abstract final class AuthRoutes {
  static List<RouteBase> get routes => [
        GoRoute(
          path: '/login',
          name: RouteNames.login,
          builder: (context, state) => const LoginPage(),
        ),
      ];
}
