import 'package:dio/dio.dart';
import 'package:flutter_appauth/flutter_appauth.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:{{project_slug}}/src/api/generated/export.dart';
import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:{{project_slug}}/src/features/auth/data/dev_auth_service.dart';
import 'package:{{project_slug}}/src/features/auth/data/gatekeeper_auth_service.dart';
import 'package:{{project_slug}}/src/features/auth/data/keycloak_auth_service.dart';
import 'package:{{project_slug}}/src/features/home/data/home_repository.dart';
import 'package:mocktail/mocktail.dart';

class MockDio extends Mock implements Dio {}

class MockAuthRepository extends Mock implements AuthRepository {}

class MockHomeRepository extends Mock implements HomeRepository {}

class MockRequestInterceptorHandler extends Mock
    implements RequestInterceptorHandler {}

class MockErrorInterceptorHandler extends Mock
    implements ErrorInterceptorHandler {}

class MockDevAuthService extends Mock implements DevAuthService {}

class MockKeycloakAuthService extends Mock implements KeycloakAuthService {}

class MockGatekeeperAuthService extends Mock implements GatekeeperAuthService {}

class MockFlutterAppAuth extends Mock implements FlutterAppAuth {}

class MockFlutterSecureStorage extends Mock implements FlutterSecureStorage {}

class MockHomeClient extends Mock implements HomeClient {}

class MockHealthClient extends Mock implements HealthClient {}
