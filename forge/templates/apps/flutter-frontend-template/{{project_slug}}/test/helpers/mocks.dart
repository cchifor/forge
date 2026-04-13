import 'package:dio/dio.dart';
import 'package:{{project_slug}}/src/api/generated/export.dart';
import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:{{project_slug}}/src/features/auth/data/dev_auth_service.dart';
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

class MockHomeClient extends Mock implements HomeClient {}

class MockHealthClient extends Mock implements HealthClient {}
