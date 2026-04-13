import 'package:flutter/foundation.dart';

/// Programmatic controller for [Sidebar] open/close state.
class SidebarController extends ChangeNotifier {
  SidebarController({bool isOpen = true}) : _isOpen = isOpen;

  bool _isOpen;

  bool get isOpen => _isOpen;

  void open() {
    if (!_isOpen) {
      _isOpen = true;
      notifyListeners();
    }
  }

  void close() {
    if (_isOpen) {
      _isOpen = false;
      notifyListeners();
    }
  }

  void toggle() {
    _isOpen = !_isOpen;
    notifyListeners();
  }
}
