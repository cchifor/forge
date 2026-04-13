import 'app_exception.dart';

String formatAppException(AppException exception) {
  return switch (exception) {
    ServerException(:final message, :final statusCode) =>
      'Server error ($statusCode): $message',
    NetworkException(:final message) =>
      'Network error: $message',
    UnauthorizedException() =>
      'Please sign in to continue.',
    NotFoundException(:final message) =>
      message,
    ConflictException(:final message) =>
      message,
    ValidationException(:final message, :final errors) =>
      errors != null && errors.isNotEmpty
          ? errors.join('\n')
          : message,
  };
}

String formatException(Object error) {
  if (error is AppException) {
    return formatAppException(error);
  }
  return 'An unexpected error occurred.';
}
