import 'package:flutter/material.dart';

/// Global navigator key for modal routes that overlay the shell.
/// Features import this to set `parentNavigatorKey` on detail/create routes.
final rootNavigatorKey = GlobalKey<NavigatorState>();
