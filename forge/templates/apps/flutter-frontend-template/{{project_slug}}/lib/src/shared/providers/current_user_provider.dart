import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../features/auth/domain/auth_state.dart';
import '../../features/auth/domain/user_model.dart';
import '../../features/auth/presentation/auth_controller.dart';

part 'current_user_provider.g.dart';

@riverpod
User? currentUser(Ref ref) {
  final authState = ref.watch(authControllerProvider).value;
  return switch (authState) {
    Authenticated(:final user) => user,
    _ => null,
  };
}
