import 'package:flutter/widgets.dart';

/// One canvas component — a name, a Flutter widget builder, and an
/// optional JSON schema for its props.
class CanvasComponent {
  final String name;
  final Widget Function(Map<String, dynamic> props) builder;
  final Map<String, dynamic>? propsSchema;

  const CanvasComponent({
    required this.name,
    required this.builder,
    this.propsSchema,
  });
}

/// Resolves component names (from backend payloads) to Flutter widget
/// builders. Mirrors the Vue/Svelte registry shape.
class CanvasRegistry {
  final Map<String, CanvasComponent> _entries = {};

  CanvasRegistry([List<CanvasComponent> initial = const []]) {
    for (final e in initial) {
      register(e);
    }
  }

  void register(CanvasComponent entry) {
    if (_entries.containsKey(entry.name)) {
      throw StateError('canvas component "${entry.name}" is already registered');
    }
    _entries[entry.name] = entry;
  }

  CanvasComponent? resolve(String name) => _entries[name];

  Iterable<CanvasComponent> entries() => _entries.values;
}
