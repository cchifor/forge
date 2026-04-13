import 'package:go_router/go_router.dart';

import '../../routing/route_names.dart';
import 'presentation/profile_page.dart';

abstract final class ProfileRoutes {
  static List<RouteBase> get routes => [
        GoRoute(
          path: '/profile',
          name: RouteNames.profile,
          builder: (context, state) => const ProfilePage(),
        ),
      ];
}
