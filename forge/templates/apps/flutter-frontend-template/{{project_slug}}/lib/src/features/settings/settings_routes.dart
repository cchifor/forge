import 'package:go_router/go_router.dart';

import '../../routing/route_names.dart';
import 'presentation/settings_page.dart';

abstract final class SettingsRoutes {
  static List<RouteBase> get routes => [
        GoRoute(
          path: '/settings',
          name: RouteNames.settings,
          builder: (context, state) => const SettingsPage(),
        ),
      ];
}
