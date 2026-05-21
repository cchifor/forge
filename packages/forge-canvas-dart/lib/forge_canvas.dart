/// Canvas registry + AG-UI SSE client + base components for
/// forge-generated Flutter applications.
library forge_canvas;

export 'src/canvas_registry.dart';
export 'src/ag_ui_client.dart';
export 'src/lint.dart';
export 'src/theme.dart';

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
//
// Contract (Initiative #8): the generated library is the SINGLE
// source of truth for canvas-component prop shapes. The components
// under `src/components/` import the generated sealed classes
// directly (`DataTableColumn`, `DynamicFormField`,
// `WorkflowDiagramNode`, `WorkflowDiagramEdge`); the old
// hand-written private mirror classes (`_Column`, `_Field`,
// `_WfNode`, `_WfEdge`) are gone. To extend a prop schema, edit the
// JSON schema and run `python -m forge.codegen.canvas_props` — the
// components inherit the new typed shape automatically.
export 'src/generated/props.dart';

// Base components — all 5 canvas components now live in the package.
export 'src/components/report.dart';
export 'src/components/code_viewer.dart';
export 'src/components/data_table.dart';
export 'src/components/dynamic_form.dart';
export 'src/components/workflow_diagram.dart';
