import 'package:{{project_slug}}/src/api/generated/export.dart';
import 'package:{{project_slug}}/src/features/home/data/home_repository.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../../helpers/mocks.dart';

void main() {
  late MockHomeClient mockHomeClient;
  late MockHealthClient mockHealthClient;
  late HomeRepository repo;

  setUp(() {
    mockHomeClient = MockHomeClient();
    mockHealthClient = MockHealthClient();
    repo = HomeRepository(
      homeClient: mockHomeClient,
      healthClient: mockHealthClient,
    );
  });

  group('HomeRepository', () {
    test('getStatus() delegates to HomeClient.getStatus()', () async {
      const expected = StatusResponse(status: 'ok');
      when(() => mockHomeClient.getStatus())
          .thenAnswer((_) async => expected);

      final result = await repo.getStatus();

      expect(result.status, 'ok');
      verify(() => mockHomeClient.getStatus()).called(1);
    });

    test('getInfo() delegates to HomeClient.getInfo()', () async {
      const expected = InfoResponse(
        title: 'Test Service',
        version: '1.0.0',
        description: 'A test service',
      );
      when(() => mockHomeClient.getInfo())
          .thenAnswer((_) async => expected);

      final result = await repo.getInfo();

      expect(result.title, 'Test Service');
      expect(result.version, '1.0.0');
      expect(result.description, 'A test service');
      verify(() => mockHomeClient.getInfo()).called(1);
    });

    test('checkHealth() delegates to HealthClient.readinessCheck()', () async {
      const expected = ReadinessResponse(status: 'healthy');
      when(() => mockHealthClient.readinessCheck())
          .thenAnswer((_) async => expected);

      final result = await repo.checkHealth();

      expect(result.status, 'healthy');
      verify(() => mockHealthClient.readinessCheck()).called(1);
    });

    test('getStatus() propagates errors from HomeClient', () async {
      when(() => mockHomeClient.getStatus())
          .thenThrow(Exception('connection failed'));

      expect(
        () => repo.getStatus(),
        throwsA(isA<Exception>()),
      );
    });

    test('getInfo() propagates errors from HomeClient', () async {
      when(() => mockHomeClient.getInfo())
          .thenThrow(Exception('connection failed'));

      expect(
        () => repo.getInfo(),
        throwsA(isA<Exception>()),
      );
    });

    test('checkHealth() propagates errors from HealthClient', () async {
      when(() => mockHealthClient.readinessCheck())
          .thenThrow(Exception('connection failed'));

      expect(
        () => repo.checkHealth(),
        throwsA(isA<Exception>()),
      );
    });
  });
}
