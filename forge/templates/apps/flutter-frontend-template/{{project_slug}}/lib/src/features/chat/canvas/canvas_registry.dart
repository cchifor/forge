import 'package:flutter/widgets.dart';

import '../domain/workspace_activity.dart';
import 'activities/canvas_fallback.dart';
import 'activities/code_viewer.dart';
import 'activities/data_table.dart';
import 'activities/dynamic_form.dart';
import 'activities/report.dart';
import 'activities/workflow_diagram.dart';

typedef CanvasBuilder = Widget Function(
  BuildContext context,
  WorkspaceActivity activity,
  void Function(WorkspaceAction)? onAction,
);

class CanvasRegistryEntry {
  const CanvasRegistryEntry({required this.builder, required this.label});
  final CanvasBuilder builder;
  final String label;
}

class CanvasRegistry {
  CanvasRegistry._();

  static final Map<String, CanvasRegistryEntry> _entries = {
    'fallback': CanvasRegistryEntry(
      label: 'Activity',
      builder: (ctx, a, _) => CanvasFallback(activity: a),
    ),
    'dynamic_form': CanvasRegistryEntry(
      label: 'Form',
      builder: (ctx, a, onAction) => DynamicFormActivity(activity: a, onAction: onAction),
    ),
    'data_table': CanvasRegistryEntry(
      label: 'Data Table',
      builder: (ctx, a, _) => DataTableActivity(activity: a),
    ),
    'report': CanvasRegistryEntry(
      label: 'Report',
      builder: (ctx, a, _) => ReportActivity(activity: a),
    ),
    'workflow': CanvasRegistryEntry(
      label: 'Workflow',
      builder: (ctx, a, _) => WorkflowDiagramActivity(activity: a),
    ),
    'code_viewer': CanvasRegistryEntry(
      label: 'Code',
      builder: (ctx, a, _) => CodeViewerActivity(activity: a),
    ),
  };

  static void register(String activityType, CanvasRegistryEntry entry) {
    _entries[activityType] = entry;
  }

  static CanvasRegistryEntry resolve(String activityType) {
    return _entries[activityType] ?? _entries['fallback']!;
  }
}
