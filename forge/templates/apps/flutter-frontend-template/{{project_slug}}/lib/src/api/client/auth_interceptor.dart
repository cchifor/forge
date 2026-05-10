import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/auth/data/auth_repository.dart';

/// Marker on the request options so a single retry attempt cannot
/// recurse on a second 401 from the retried call.
const _retriedFlag = '__authInterceptorRetried';

class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._ref, {Dio? dio}) : _dio = dio;

  final Ref _ref;
  // Used to retry the original request after a refresh-token rotation.
  // Injected lazily because the Dio that owns this interceptor is
  // constructed in the same provider that builds the interceptor; the
  // dio_client.dart factory calls bindDio after add(interceptor).
  Dio? _dio;

  /// Bind the owning Dio instance for the 401-retry path. Called once
  /// from `dio_client.dart` after the interceptor is registered.
  void bindDio(Dio dio) {
    _dio ??= dio;
  }

  @override
  void onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) {
    // On web, auth is handled by Gatekeeper HttpOnly cookies — no Bearer token.
    if (!kIsWeb) {
      final authRepo = _ref.read(authRepositoryProvider);
      final token = authRepo.accessToken;
      if (token != null) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    }
    handler.next(options);
  }

  /// Native 401 → refresh-token rotation → single retry.
  ///
  /// Mirrors the standard mobile-OIDC pattern: when the server rejects
  /// the access token (typical when a backend access token's TTL is
  /// shorter than the client's idle timeout), rotate via the refresh
  /// token and replay the original request with the new bearer.
  ///
  /// Web is a no-op — the cookie-based BFF lets the API layer's
  /// redirect handler land the user back at `/auth/login`.
  ///
  /// Single-retry semantics: a second 401 surfaces as-is so the caller
  /// can navigate to login (refresh token revoked / expired).
  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (kIsWeb || err.response?.statusCode != 401) {
      handler.next(err);
      return;
    }
    final options = err.requestOptions;
    if (options.extra[_retriedFlag] == true) {
      // Already retried once. Surface the second failure so the
      // caller can navigate to login.
      handler.next(err);
      return;
    }
    final dio = _dio;
    if (dio == null) {
      // Interceptor wasn't bound yet; can't retry. Fail open.
      handler.next(err);
      return;
    }
    final authRepo = _ref.read(authRepositoryProvider);
    try {
      await authRepo.refreshAccessToken();
    } catch (_) {
      // Refresh token rejected. Force logout; surface original 401
      // so the caller can land at the login screen.
      await authRepo.logout();
      handler.next(err);
      return;
    }
    // Mark and retry. The Bearer header will be re-injected by
    // onRequest with the freshly rotated access token.
    options.extra[_retriedFlag] = true;
    options.headers.remove('Authorization');
    try {
      final response = await dio.fetch(options);
      handler.resolve(response);
    } on DioException catch (retryErr) {
      handler.next(retryErr);
    }
  }
}
