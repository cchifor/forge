# Changelog

## 1.0.0-alpha.6 — unreleased

- **Breaking:** `AgUiClient` is now generic over event type `E` and takes a
  caller-supplied `parser: (Map<String, dynamic>) -> E?`. This lets
  generated apps keep their own typed `AgUiEvent` sealed-class hierarchy
  instead of the package's untyped value class. New `runAgent({threadId,
  runId, messages, state, forwardedProps, bearerToken})` helper matches
  the deepagent `POST /agent/run` contract directly. Reconnect +
  `Last-Event-ID` resume are now opt-in via `reconnect: true` (off by
  default to preserve the deepagent one-shot semantic). v2 Theme 9
  consolidated the deprecated Flutter-template-local `AgUiClient` into
  this package.
- **Breaking (canvas props):** Generated prop classes are now `final
  class` and lift nested-object array items into typed inner classes:
  `DataTableProps.columns` is `List<DataTableColumn>` (was
  `List<Map<String, dynamic>>`); `DynamicFormProps.fields` is
  `List<DynamicFormField>`; `WorkflowDiagramProps.nodes` /
  `.edges` are `List<WorkflowDiagramNode>` / `List<WorkflowDiagramEdge>`.
  Apps that constructed these props directly (or read `columns[i]` as
  a map) need to switch to the new typed shape — `*.fromJson(...)` /
  `.toJson()` still accept and emit the existing wire format, so
  payloads parsed off the agent stream are unaffected.
  `DataTableProps.rows` keeps `List<Map<String, dynamic>>` on purpose
  (its schema sets `additionalProperties: true`, no fixed shape).
  Inside `forge_canvas`, the `DataTable`, `DynamicForm`, and
  `WorkflowDiagram` widgets dropped their private `_Column`, `_Field`,
  `_WfNode`, and `_WfEdge` mirror classes; `CodeViewer.fromProps` /
  `Report.fromProps` now route through `CodeViewerProps.fromJson` /
  `ReportProps.fromJson` so the generated module is the single source
  of truth at parse time. The widgets' own constructors are unchanged.

## 1.0.0-alpha.1 — unreleased

- Initial scaffold. `CanvasRegistry`, `AgUiClient` with exponential-backoff
  reconnect + `Last-Event-ID` resume, `ForgeTheme` (shadcn-flavored
  Material 3). Real component extraction lands in `1.0.0-alpha.4`.
