import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../errors/app_exception.dart';

extension AsyncValueX<T> on AsyncValue<T> {
  bool get isRefreshing => isLoading && hasValue;

  AppException? get appException {
    if (this case AsyncError(:final error)) {
      if (error is AppException) return error;
    }
    return null;
  }
}
