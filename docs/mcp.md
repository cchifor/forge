# MCP (Model Context Protocol) in forge

The [Model Context Protocol](https://modelcontextprotocol.io/) lets LLM agents discover and invoke tools declared by external servers. Forge-generated projects treat MCP as first-class: the backend exposes a tool registry, the frontend ships a discovery panel + approval UI, and the canvas system renders MCP-extension UIs inside sandboxed iframes.

## What ships out-of-the-box (1.0.0a1 scaffold)

- **Protocol types** — `McpExtPayload` in `forge/templates/_shared/ui-protocol/mcp_ext_payload.schema.json` plus generated Python / TS / Dart counterparts.
- **Iframe sandbox** — the canvas engine treats `{engine: "mcp-ext", html, initialContext}` payloads as MCP tool UIs and renders them in a sandboxed iframe.
- **ApprovalMode enum** — `auto | prompt-once | prompt-every` (shared YAML at `forge/templates/_shared/domain/enums/approval_mode.yaml`).

## What's scaffolded for Phase 3.4 rollout

- `mcp.config.json` skeleton at project root (one entry per connected MCP server).
- Backend router at `src/app/mcp/router.py` exposing `GET /mcp/tools` (tool discovery) and `POST /mcp/invoke` (proxied tool calls).
- Frontend **Tool Discovery** panel listing registered tools with summaries.
- Frontend **Approval Dialog** with the three approval modes.

## Planned rollout

| Alpha | Deliverable |
|---|---|
| 1.0.0a1 (this) | Protocol types + iframe sandbox + approval mode enum |
| 1.0.0a2 | `mcp.config.json` format + backend router scaffold |
| 1.0.0a3 | Tool Discovery panel (Vue + Svelte + Flutter) |
| 1.0.0a4 | Approval Dialog (Vue + Svelte + Flutter) + docs/mcp-integration-guide.md |

## Configuration shape (preview)

The `mcp.config.json` will look like:

```json
{
  "$schema": "https://forge.dev/schemas/mcp-config-v1.json",
  "version": 1,
  "defaultApprovalMode": "prompt-once",
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/sandbox"],
      "approvalMode": "auto"
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "${env.GITHUB_TOKEN}" },
      "approvalMode": "prompt-every"
    }
  }
}
```

## Approval-mode semantics

- `auto` — tool calls execute immediately. Appropriate for read-only / idempotent tools.
- `prompt-once` — the user grants per-session approval for a tool the first time it's called. Default.
- `prompt-every` — every invocation surfaces the approval dialog. Appropriate for destructive / high-blast-radius tools.

The approval choice is persisted in the user's session; `forge migrate-mcp` (post-1.0.0a4 codemod) will upgrade existing projects that hand-rolled the approval flow.

## Iframe sandbox

`McpExtPayload` UIs render inside an iframe with:

```html
<iframe sandbox="allow-scripts" srcdoc="{{ payload.html }}">
```

The iframe receives `payload.initialContext` via `postMessage` on load. This gives MCP extensions a safe surface to render arbitrary UI while the canvas keeps them isolated from the host origin.

See `forge/templates/_shared/ui-protocol/mcp_ext_payload.schema.json` for the full wire shape.
