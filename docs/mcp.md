# MCP (Model Context Protocol) in forge

The [Model Context Protocol](https://modelcontextprotocol.io/) lets LLM agents discover and invoke tools declared by external servers. Forge-generated projects treat MCP as first-class: the backend exposes a tool registry, the frontend ships a discovery panel + approval UI, and the canvas system renders MCP-extension UIs inside sandboxed iframes.

## What ships out-of-the-box (1.0.0a1 scaffold)

- **Protocol types** — `McpExtPayload` in `forge/templates/_shared/ui-protocol/mcp_ext_payload.schema.json` plus generated Python / TS / Dart counterparts.
- **Iframe sandbox** — the canvas engine treats `{engine: "mcp-ext", html, initialContext}` payloads as MCP tool UIs and renders them in a sandboxed iframe.
- **ApprovalMode enum** — `auto | prompt-once | prompt-every` (shared YAML at `forge/templates/_shared/domain/enums/approval_mode.yaml`).

## What's scaffolded for Phase 3.4 rollout

- `mcp.config.json` skeleton at project root (one entry per connected MCP server).
- Backend router at `src/app/mcp/router.py` exposing `GET /mcp/tools` (tool discovery), `POST /mcp/invoke` (proxied tool calls), and `GET /mcp/audit?limit=N` (read the last N audit-log entries — for operators / debug UIs).
- Frontend **Tool Discovery** panel listing registered tools with summaries.
- Frontend **Approval Dialog** with the three approval modes.

### Audit endpoint

`GET /mcp/audit?limit=N` returns the last `N` (1 ≤ N ≤ 1000, default 50) entries from the JSONL audit log written by `record_invocation`, **most-recent-first**:

```json
{
  "entries": [
    {
      "ts": 1700000000.0,
      "user_id": "user-42",
      "server": "fs",
      "tool": "read_file",
      "input_hash": "abc123",
      "decision": "approved",
      "error": null
    }
  ]
}
```

The endpoint is **read-only and additive** — the write path is unchanged. A missing log file (no calls yet) returns `{"entries": []}`. Storage IO failures surface as `500` so monitoring catches them; invalid `limit` values surface as `422` via FastAPI's `Query` validator. Decisions in the wire shape match the on-disk vocabulary: `approved`, `auto`, `rejected-bad-token`, plus any `error` string when the downstream tool call raised.

## Rollout history

**Live now (1.2.0):** the MCP protocol types, the iframe sandbox + approval-mode
enum, the `mcp.config.json` format, and the backend router (`/mcp/tools`,
`/mcp/invoke`, and the [audit endpoint](#audit-endpoint) above). The frontend
Tool Discovery / Approval Dialog panels are the remaining roadmap items.

The table below records the original per-alpha sequencing of the capability (the
current release is `1.2.0`, not `1.0.0a1`):

| Alpha | Deliverable |
|---|---|
| 1.0.0a1 | Protocol types + iframe sandbox + approval mode enum |
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
