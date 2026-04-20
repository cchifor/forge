import 'package:flutter/foundation.dart';

/// Runtime lint for canvas component props.
///
/// Dev-mode (`!kReleaseMode`) only: compares the payload props against
/// the component's registered JSON Schema and emits `debugPrint` on each
/// mismatch so prop drift surfaces in the Flutter logs instead of
/// silently rendering a blank widget.

class LintIssue {
  final String field;
  final String message;

  const LintIssue({required this.field, required this.message});

  @override
  String toString() => '$field: $message';
}

List<LintIssue> lintProps(
  Map<String, dynamic>? propsSchema,
  Map<String, dynamic> props,
) {
  if (propsSchema == null) return const [];

  final issues = <LintIssue>[];
  final properties = (propsSchema['properties'] as Map<String, dynamic>?) ?? const {};
  final required = (propsSchema['required'] as List<dynamic>?)?.cast<String>() ?? const [];
  final additionalOk = propsSchema['additionalProperties'] == true;

  for (final name in required) {
    if (!props.containsKey(name)) {
      issues.add(LintIssue(field: name, message: 'required prop is missing'));
    }
  }

  for (final entry in props.entries) {
    final schema = properties[entry.key] as Map<String, dynamic>?;
    if (schema == null) {
      if (!additionalOk) {
        issues.add(LintIssue(field: entry.key, message: 'unknown prop'));
      }
      continue;
    }
    final ty = schema['type'] as String?;
    final value = entry.value;
    if (ty == 'string' && value is! String) {
      issues.add(LintIssue(field: entry.key, message: 'expected string, got ${value.runtimeType}'));
    } else if (ty == 'integer' && value is! int) {
      issues.add(LintIssue(field: entry.key, message: 'expected integer, got ${value.runtimeType}'));
    } else if (ty == 'number' && value is! num) {
      issues.add(LintIssue(field: entry.key, message: 'expected number, got ${value.runtimeType}'));
    } else if (ty == 'boolean' && value is! bool) {
      issues.add(LintIssue(field: entry.key, message: 'expected boolean, got ${value.runtimeType}'));
    } else if (ty == 'array' && value is! List) {
      issues.add(LintIssue(field: entry.key, message: 'expected array, got ${value.runtimeType}'));
    } else if (ty == 'object' && value is! Map) {
      issues.add(LintIssue(field: entry.key, message: 'expected object, got ${value.runtimeType}'));
    }
    final enumValues = schema['enum'] as List<dynamic>?;
    if (enumValues != null && !enumValues.contains(value)) {
      issues.add(LintIssue(field: entry.key, message: 'not in enum $enumValues'));
    }
  }

  return issues;
}

void warnOnLintIssues(String componentName, List<LintIssue> issues) {
  if (issues.isEmpty || kReleaseMode) return;
  debugPrint('[forge:canvas] $componentName: ${issues.length} prop lint issue(s):');
  for (final issue in issues) {
    debugPrint('  $issue');
  }
}
