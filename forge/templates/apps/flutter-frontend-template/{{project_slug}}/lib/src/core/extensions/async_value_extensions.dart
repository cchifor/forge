import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../errors/app_exception.dart';

extension AsyncValueX<T> on AsyncValue<T> {
  // NOTE: `isRefreshing` used to live here, but flutter_riverpod 3.x added its
  // own `AsyncValueExtensions.isRefreshing`, creating an ambiguity. Use the
  // built-in one directly.

  AppException? get appException {
    if (this case AsyncError(:final error)) {
      if (error is AppException) return error;
    }
    return null;
  }
}
