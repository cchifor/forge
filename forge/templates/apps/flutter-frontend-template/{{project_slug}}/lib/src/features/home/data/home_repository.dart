import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../api/client/rest_client_provider.dart';
import '../../../api/generated/export.dart';

part 'home_repository.g.dart';

class HomeRepository {
  HomeRepository({
    required HomeClient homeClient,
    required HealthClient healthClient,
  })  : _homeClient = homeClient,
        _healthClient = healthClient;

  final HomeClient _homeClient;
  final HealthClient _healthClient;

  Future<StatusResponse> getStatus() => _homeClient.getStatus();

  Future<InfoResponse> getInfo() => _homeClient.getInfo();

  Future<ReadinessResponse> checkHealth() => _healthClient.readinessCheck();
}

@riverpod
HomeRepository homeRepository(Ref ref) {
  final client = ref.watch(restClientProvider);
  return HomeRepository(
    homeClient: client.home,
    healthClient: client.health,
  );
}

@riverpod
Future<InfoResponse> serviceInfo(Ref ref) async {
  final repo = ref.watch(homeRepositoryProvider);
  return repo.getInfo();
}

@riverpod
Future<ReadinessResponse> healthCheck(Ref ref) async {
  final repo = ref.watch(homeRepositoryProvider);
  return repo.checkHealth();
}
