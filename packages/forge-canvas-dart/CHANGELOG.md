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

## 1.0.0-alpha.1 — unreleased

- Initial scaffold. `CanvasRegistry`, `AgUiClient` with exponential-backoff
  reconnect + `Last-Event-ID` resume, `ForgeTheme` (shadcn-flavored
  Material 3). Real component extraction lands in `1.0.0-alpha.4`.
