# AG-UI SSE agent endpoint — hardening & deferred gaps

The `agent_agui` fragment serves the **canonical** AG-UI Server-Sent-Events
transport at `POST /api/v1/agent` (see
`src/app/api/v1/endpoints/agui.py`). It reuses the same pydantic-ai agent
build (`app.agents.llm_runner.build_agent`) and `tool_registry` as the legacy
WebSocket endpoint at `/api/v1/ws/agent`.

This tranche makes **conversational chat work end-to-end** (RUN_STARTED →
TEXT_MESSAGE_* → tool-call streaming display → RUN_FINISHED), parsed by the
existing frontend with no frontend code change beyond `VITE_AGENT_BASE_URL`.

The following are **intentionally deferred** and NOT shipped here.

## Deferred-tool RESUME round-trip (the #27 follow-on)

`AGUIAdapter` exposes the request body's `tools` as a pydantic-ai
`ExternalToolset` and ends the run with the tool call — but *resuming* the run
requires the follow-up POST to carry the assistant `toolCalls` plus a matching
`tool` result message (or `deferred_tool_results`). The generated
`useAgentClient` currently sends only `{id, role, content}` (+
`forwardedProps.hitl_response`, which the base adapter ignores), so the loop
does not yet close.

This tranche makes the loop **possible** (the backend is ready); closing it
needs frontend changes — persist `toolCalls`/`tool` messages in
`snapshot.messages` so the resume POST replays them. That is the #27
follow-on. Until then, server-side tool *results* emit upstream
`TOOL_CALL_RESULT` (which canvas-core treats as UNKNOWN / no-op — fine for a
status-only UI), and `THINKING_*` events likewise parse as UNKNOWN (harmless).

## `include_chat` without `agent.llm`

`agent_agui` is enabled by `agent.llm` (the AG-UI adapter needs a pydantic-ai
agent). An `include_chat` project WITHOUT `agent.llm` renders a chat UI with
**no SSE backend** behind it — pre-existing (real responses always required
`agent.llm`), out of scope here. Enable `agent.llm` to wire the backend.

## Production hardening (deferred)

- **Rate / cost / body-size limits** — the endpoint spends LLM budget and runs
  server-side tools per request. It is auth-gated (`Depends(get_current_user)`,
  same posture as `/api/v1/tools`) but has no per-tenant rate limit or token/cost
  ceiling yet — add these before public exposure. A request-body size cap IS
  enforced globally by the base template's `ContentSizeLimitMiddleware`
  (`audit.max_body_size`, default 50 KiB); note the AG-UI client replays the full
  message history on every turn, so you will likely need to RAISE that limit for
  multi-turn chats.
- **Client-disconnect cancellation** — the run should stop when the client
  disconnects. The base Starlette `StreamingResponse` covers basic teardown;
  add explicit disconnect polling and/or a `ModelSettings.timeout` if your
  provider does not abort promptly.
- **`threadId` → conversation persistence** — this tranche is first-run
  streaming only. The body's `threadId`/`runId` are not yet persisted to a
  conversation repository, so there is no server-side history/reconnect story.
  Wire `threadId` to the conversation persistence layer to gain durable
  history and resume-after-reconnect.
