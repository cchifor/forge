import 'package:riverpod_annotation/riverpod_annotation.dart';
import 'package:shared_preferences/shared_preferences.dart';

part 'key_value_storage.g.dart';

@Riverpod(keepAlive: true)
SharedPreferences keyValueStorage(Ref ref) {
  throw UnimplementedError(
    'keyValueStorageProvider must be overridden with a real SharedPreferences instance',
  );
}
