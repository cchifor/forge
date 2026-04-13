import 'package:go_router/go_router.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../features/auth/auth_routes.dart';
import '../features/auth/domain/auth_state.dart';
import '../features/auth/presentation/auth_controller.dart';
import '../features/home/home_routes.dart';
// --- feature imports ---
import '../features/profile/profile_routes.dart';
import '../features/settings/settings_routes.dart';
import 'navigator_keys.dart';
import 'scaffold_with_nav.dart';

part 'app_router.g.dart';

@Riverpod(keepAlive: true)
GoRouter goRouter(Ref ref) {
  final authState = ref.watch(authControllerProvider);

  return GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/',
    redirect: (context, state) {
      final isAuthenticated = authState.value is Authenticated;
      final isLoginRoute = state.matchedLocation == '/login';

      if (!isAuthenticated && !isLoginRoute) return '/login';
      if (isAuthenticated && isLoginRoute) return '/';
      return null;
    },
    routes: [
      // Auth (outside shell)
      ...AuthRoutes.routes,

      // Shell with navigation
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) {
          return ScaffoldWithNav(navigationShell: navigationShell);
        },
        branches: [
          StatefulShellBranch(routes: HomeRoutes.routes),
          // --- feature branches ---
          StatefulShellBranch(routes: ProfileRoutes.routes),
          StatefulShellBranch(routes: SettingsRoutes.routes),
        ],
      ),
    ],
  );
}
