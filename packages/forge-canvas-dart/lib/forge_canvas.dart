/// Canvas registry + AG-UI SSE client + base components for
/// forge-generated Flutter applications.
library forge_canvas;

export 'src/canvas_registry.dart';
export 'src/ag_ui_client.dart';
export 'src/lint.dart';
export 'src/theme.dart';

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
// The hand-written private _Column / _Field / _Node classes inside
// each component remain in place for now; deletion in favour of the
// generated classes is deferred to Theme 1C once the codegen
// pipeline gates drift in CI.
export 'src/generated/props.dart';

// Base components — all 5 canvas components now live in the package.
export 'src/components/report.dart';
export 'src/components/code_viewer.dart';
export 'src/components/data_table.dart';
export 'src/components/dynamic_form.dart';
export 'src/components/workflow_diagram.dart';
