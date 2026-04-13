import 'package:go_router/go_router.dart';

import '../../routing/route_names.dart';
import 'presentation/home_page.dart';

abstract final class HomeRoutes {
  static List<RouteBase> get routes => [
        GoRoute(
          path: '/',
          name: RouteNames.home,
          builder: (context, state) => const HomePage(),
        ),
      ];
}
