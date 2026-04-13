import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../generated/rest_client.dart';
import 'dio_client.dart';

part 'rest_client_provider.g.dart';

@Riverpod(keepAlive: true)
RestClient restClient(Ref ref) {
  return RestClient(ref.watch(dioProvider));
}
