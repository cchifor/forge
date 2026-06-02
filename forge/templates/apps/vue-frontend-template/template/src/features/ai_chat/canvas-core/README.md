# canvas-core (vendored)

Framework-agnostic AG-UI runtime — the protocol reducer, SSE client, and MCP
bridge that the chat UI builds on. This is **vendored source**: forge copies it
into the generated project instead of pinning a published `@forge/canvas-core`
package, so your project is self-contained and you own this code.

Imported throughout the chat feature as `@forge/canvas-core` (aliased to this
directory in `tsconfig.app.json` `paths` + `vite.config.ts` `resolve.alias`).
You're free to edit, extend, or extract-and-publish it — it's yours.
