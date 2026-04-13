import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'src/app.dart';
import 'src/core/errors/error_page.dart';
import 'src/core/storage/key_value_storage.dart';

Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Replace the default error widget in release/profile modes
  if (!kDebugMode) {
    ErrorWidget.builder = (details) => AppErrorWidget(details: details);
  }

  final sharedPreferences = await SharedPreferences.getInstance();

  runApp(
    ProviderScope(
      overrides: [
        keyValueStorageProvider.overrideWithValue(sharedPreferences),
      ],
      child: const App(),
    ),
  );
}
