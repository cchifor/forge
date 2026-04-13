import 'package:freezed_annotation/freezed_annotation.dart';

import 'user_model.dart';

part 'auth_state.freezed.dart';

@freezed
abstract class AuthState with _$AuthState {
  const factory AuthState.authenticated({
    required User user,
    required String accessToken,
  }) = Authenticated;

  const factory AuthState.unauthenticated() = Unauthenticated;
}
