import 'package:freezed_annotation/freezed_annotation.dart';

part 'app_exception.freezed.dart';

@freezed
sealed class AppException with _$AppException implements Exception {
  const factory AppException.server({
    required int statusCode,
    required String message,
    String? type,
    Map<String, dynamic>? detail,
  }) = ServerException;

  const factory AppException.network({
    required String message,
  }) = NetworkException;

  const factory AppException.unauthorized({
    @Default('Authentication required') String message,
  }) = UnauthorizedException;

  const factory AppException.notFound({
    required String message,
  }) = NotFoundException;

  const factory AppException.conflict({
    required String message,
  }) = ConflictException;

  const factory AppException.validation({
    required String message,
    List<String>? errors,
  }) = ValidationException;
}
