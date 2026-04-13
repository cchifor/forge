import 'package:freezed_annotation/freezed_annotation.dart';

part 'user_model.freezed.dart';
part 'user_model.g.dart';

@freezed
abstract class User with _$User {
  const factory User({
    required String id,
    required String username,
    required String email,
    @JsonKey(name: 'first_name') required String firstName,
    @JsonKey(name: 'last_name') required String lastName,
    @Default([]) List<String> roles,
    @JsonKey(name: 'customer_id') required String customerId,
    @JsonKey(name: 'org_id') String? orgId,
  }) = _User;

  factory User.fromJson(Map<String, dynamic> json) => _$UserFromJson(json);

  factory User.fromJwtClaims(Map<String, dynamic> claims) {
    final realmAccess = claims['realm_access'] as Map<String, dynamic>?;
    final roles = (realmAccess?['roles'] as List<dynamic>?)
            ?.map((e) => e.toString())
            .toList() ??
        [];

    return User(
      id: claims['sub']?.toString() ?? '',
      username: claims['preferred_username']?.toString() ?? '',
      email: claims['email']?.toString() ?? '',
      firstName: claims['given_name']?.toString() ?? '',
      lastName: claims['family_name']?.toString() ?? '',
      roles: roles,
      customerId:
          claims['customer_id']?.toString() ?? claims['sub']?.toString() ?? '',
      orgId: claims['org_id']?.toString(),
    );
  }

  const User._();

  String get fullName => '$firstName $lastName'.trim();
  bool hasRole(String role) => roles.contains(role);
  bool get isAdmin => hasRole('admin');
}
