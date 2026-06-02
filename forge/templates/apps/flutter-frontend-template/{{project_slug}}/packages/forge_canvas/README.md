# forge_canvas

Canvas registry + AG-UI SSE client for forge-generated Flutter applications.

**Status:** `1.0.0-alpha.1` scaffold. Phase 3.1 of the forge 1.0 roadmap.

## What this package provides

- `CanvasRegistry` — maps component_name strings (from backend payloads) to Flutter widget builders
- `AgUiClient<E>` — generic SSE client with optional exponential-backoff reconnect and `Last-Event-ID` resume; the event type and parser are caller-supplied so apps keep their own typed event union
- `ForgeTheme` — shadcn-flavored Material 3 theme matching `@forge/canvas-vue` and `@forge/canvas-svelte`

## Installing

```yaml
dependencies:
  forge_canvas: ^1.0.0-alpha.6
```

## Usage

```dart
import 'package:forge_canvas/forge_canvas.dart';

final registry = CanvasRegistry([
  CanvasComponent(
    name: 'DataTable',
    builder: (props) => MyDataTable(props: props),
  ),
]);

// Generated apps ship a sealed `AgUiEvent` hierarchy with a `parse(json)`
// factory. The client is generic over it:
final client = AgUiClient<AgUiEvent>(
  dio: Dio(),
  parser: AgUiEvent.parse,
  onParseError: (raw) => UnknownEvent(type: '__parse_error__', raw: {'data': raw}),
);

await for (final event in client.runAgent(
  threadId: 't1',
  runId: 'r1',
  messages: [{'role': 'user', 'content': 'hello'}],
)) {
  // handle event
}
```

## Roadmap

- `1.0.0-alpha.1` (this) — scaffold: registry + SSE client + theme
- `1.0.0-alpha.4` — real component implementations (`CodeViewer`, `DataTable`, `DynamicForm`, `Report`, `WorkflowDiagram`)
- `1.0.0` — GA

## Prop-shape contract

The classes under `lib/src/generated/props.dart` are the **single
source of truth** for canvas-component prop shapes. They are emitted
from `forge/templates/_shared/canvas-components/*.props.schema.json`
by `python -m forge.codegen.canvas_props` and ship sealed inner
classes for nested-object array items
(`DynamicFormProps.fields` is `List<DynamicFormField>`,
`DataTableProps.columns` is `List<DataTableColumn>`,
`WorkflowDiagramProps.nodes/edges` are `List<WorkflowDiagramNode>` /
`List<WorkflowDiagramEdge>`).

Rules:

- The package's public surface (`forge_canvas.dart`) re-exports only
  the generated classes. The components under `lib/src/components/`
  import the generated sealed classes directly and no longer carry
  private mirror classes (the old `_Column`, `_Field`, `_WfNode`,
  `_WfEdge` are gone).
- Hand-written prop mirror classes inside component files are
  **banned**: the codegen pipeline tests grep for them and will fail
  CI.
- `DataTableProps.rows` keeps its `List<Map<String, dynamic>>` typing
  on purpose — its schema sets `additionalProperties: true` and
  there is no fixed shape to type against.
- To extend a prop schema, edit the JSON schema and re-run the
  codegen — components inherit the new typed shape automatically.

See [forge repository](https://github.com/forge-project/forge) for the broader 1.0 roadmap.
