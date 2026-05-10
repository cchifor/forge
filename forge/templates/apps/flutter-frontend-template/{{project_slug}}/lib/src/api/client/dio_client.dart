import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../core/config/env_config.dart';
import 'auth_interceptor.dart';
import 'error_interceptor.dart';
import 'logging_interceptor.dart';

part 'dio_client.g.dart';

@Riverpod(keepAlive: true)
EnvConfig envConfig(Ref ref) {
  return EnvConfig.fromEnvironment();
}

@Riverpod(keepAlive: true)
Dio dio(Ref ref) {
  final config = ref.watch(envConfigProvider);
  final dio = Dio(
    BaseOptions(
      baseUrl: config.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
      headers: {'Accept': 'application/json'},
      contentType: 'application/json',
      // On web, send cookies for Gatekeeper ForwardAuth
      extra: kIsWeb ? {'withCredentials': true} : null,
    ),
  );

  final authInterceptor = AuthInterceptor(ref);
  dio.interceptors.addAll([
    authInterceptor,
    ErrorInterceptor(),
    if (config.isDevelopment) LoggingInterceptor(),
  ]);
  // Bind after registration so the interceptor's 401-retry path can
  // replay the original request with the rotated bearer token. The
  // dio reference can't be passed to the ctor (it doesn't exist yet
  // at that point in the provider).
  authInterceptor.bindDio(dio);

  return dio;
}
