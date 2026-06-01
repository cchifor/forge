import 'package:flutter/widgets.dart';

import 'lint.dart';

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

/// Resolution result: the matched component plus any lint issues found
/// against the provided props (empty in release mode).
class CanvasResolution {
  final CanvasComponent entry;
  final List<LintIssue> issues;

  const CanvasResolution({required this.entry, required this.issues});
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

  /// Resolve + validate props against the component's schema.
  CanvasResolution? lintAndResolve(String name, Map<String, dynamic> props) {
    final entry = _entries[name];
    if (entry == null) return null;
    final issues = lintProps(entry.propsSchema, props);
    warnOnLintIssues(entry.name, issues);
    return CanvasResolution(entry: entry, issues: issues);
  }

  Iterable<CanvasComponent> entries() => _entries.values;
}
