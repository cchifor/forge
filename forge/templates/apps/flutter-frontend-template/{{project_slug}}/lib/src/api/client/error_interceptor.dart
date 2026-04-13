import 'package:dio/dio.dart';

import '../../core/errors/app_exception.dart';
import '../generated/export.dart';

class ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final response = err.response;

    if (err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.sendTimeout ||
        err.type == DioExceptionType.receiveTimeout ||
        err.type == DioExceptionType.connectionError) {
      handler.reject(
        DioException(
          requestOptions: err.requestOptions,
          error: AppException.network(
            message: _networkMessage(err.type),
          ),
          type: err.type,
        ),
      );
      return;
    }

    if (response == null) {
      handler.reject(
        DioException(
          requestOptions: err.requestOptions,
          error: const AppException.network(
            message: 'No response from server',
          ),
          type: err.type,
        ),
      );
      return;
    }

    final apiError = _parseApiError(response);
    final statusCode = response.statusCode ?? 500;

    final appException = switch (statusCode) {
      401 => AppException.unauthorized(message: apiError?.message ?? 'Authentication required'),
      403 => AppException.unauthorized(message: apiError?.message ?? 'Access denied'),
      404 => AppException.notFound(message: apiError?.message ?? 'Resource not found'),
      409 => AppException.conflict(message: apiError?.message ?? 'Resource conflict'),
      422 => AppException.validation(
          message: apiError?.message ?? 'Validation failed',
          errors: apiError?.detail?.errors,
        ),
      _ => AppException.server(
          statusCode: statusCode,
          message: apiError?.message ?? 'Server error',
          type: apiError?.type,
          detail: response.data is Map<String, dynamic>
              ? response.data as Map<String, dynamic>
              : null,
        ),
    };

    handler.reject(
      DioException(
        requestOptions: err.requestOptions,
        response: response,
        error: appException,
        type: err.type,
      ),
    );
  }

  ErrorResponse? _parseApiError(Response<dynamic> response) {
    try {
      if (response.data is Map<String, dynamic>) {
        return ErrorResponse.fromJson(
          response.data as Map<String, Object?>,
        );
      }
    } catch (_) {}
    return null;
  }

  String _networkMessage(DioExceptionType type) => switch (type) {
        DioExceptionType.connectionTimeout => 'Connection timed out',
        DioExceptionType.sendTimeout => 'Request timed out',
        DioExceptionType.receiveTimeout => 'Response timed out',
        DioExceptionType.connectionError =>
          'Unable to connect. Check your network.',
        _ => 'Network error',
      };
}
