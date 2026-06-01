# Vendored canvas packages

`forge_canvas` (Flutter chat: AG-UI SSE client + canvas registry + theme) and
its pure-Dart core `forge_canvas_core` are **vendored** into this project rather
than pinned to a published pub.dev package. Your project is self-contained and
you own this code — edit, extend, or extract-and-publish it as you like.

The app's `pubspec.yaml` references `forge_canvas` via a local `path:` dep; that
package in turn resolves `forge_canvas_core` from its sibling here.
