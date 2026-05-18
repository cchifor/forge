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

See [forge repository](https://github.com/forge-project/forge) for the broader 1.0 roadmap.
