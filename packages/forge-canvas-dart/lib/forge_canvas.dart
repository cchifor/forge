/// Canvas registry + AG-UI SSE client for forge-generated Flutter applications.
///
/// Phase 3.1 of the 1.0 roadmap — scaffold. The real package lands once
/// the Flutter template's hand-rolled SSE and canvas code is extracted
/// into this library. Matches @forge/canvas-vue and @forge/canvas-svelte
/// in shape; production-grade SSE reconnect is added in Phase 3.2.
library forge_canvas;

export 'src/canvas_registry.dart';
export 'src/ag_ui_client.dart';
export 'src/lint.dart';
export 'src/theme.dart';

// Base components — Report is the 1.0.0a4 extraction reference.
// Remaining widgets (CodeViewer, DataTable, DynamicForm,
// WorkflowDiagram) land in 1.0.0a5 following the same recipe.
export 'src/components/report.dart';
