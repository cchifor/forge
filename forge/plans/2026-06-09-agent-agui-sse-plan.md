# Unify the generated agent backend on the AG-UI SSE protocol

## Context

forge's generated agentic chat has a **protocol split-brain** (a verified prod-readiness gap):

- The generated **frontend** (`useAgentClient` on the vendored `canvas-core`) POSTs `RunAgentInput`
  (`{threadId, runId, messages, state, tools, context, forwardedProps}`) to `VITE_AGENT_BASE_URL` and
  consumes **AG-UI SSE**: single-channel `data: {json}\n\n` frames, SCREAMING_CASE `type`, camelCase
  fields (`messageId`, `toolCallId`, `toolCallName`, `delta`, `snapshot`). The `event:` line is ignored.
- The generated **backend** serves a **WebSocket** at `/api/v1/ws/agent` emitting a *different*,
  snake_case `AgentEvent` union. **Nothing serves the SSE endpoint the frontend calls**, so the chat
  does not work end-to-end.

**Decisive discovery (codex-verified against platform's installed `pydantic-ai-slim==1.74.0` +
`ag-ui-protocol==0.1.14`):** platform's AG-UI SSE backend is almost entirely upstream:
`pydantic_ai.ui.ag_ui.AGUIAdapter`/`AGUIEventStream` + `ag_ui.encoder.EventEncoder` (which frames
`data: <model_dump_json(by_alias=True, exclude_none=True)>\n\n` → SCREAMING_CASE `type` + camelCase
aliases — **exactly what forge's canvas-core parses**). forge already uses pydantic-ai. So unifying is
*adding an AGUIAdapter-backed SSE endpoint that reuses forge's existing pydantic-ai agent + tools*; we
write no event-translation code.

## Scope of THIS tranche (what it does and does NOT deliver)

**Delivers:** the generated backend speaks AG-UI SSE; **conversational chat works end-to-end**
(RUN_STARTED → TEXT_MESSAGE_* → tool-call *streaming* (display) → RUN_FINISHED), parsed by the existing
frontend with **zero frontend code change** beyond the agent-URL env.

**Explicitly deferred (NOT in this tranche):** the **deferred frontend-tool round-trip** (#27). codex
confirmed it is *not* free: `AGUIAdapter` exposes `RunAgentInput.tools` as a pydantic-ai `ExternalToolset`
and ends the run with the tool call, but *resuming* requires the follow-up POST to carry the assistant
`toolCalls` + a matching `tool` result message (or `deferred_tool_results`). forge's current
`useAgentClient` sends only `{id, role, content}` + `forwardedProps.hitl_response` (which the base adapter
ignores). Completing the loop needs frontend changes (persist `toolCalls`/`tool` messages in
`snapshot.messages`) — that is the #27 follow-on. This tranche makes the loop *possible* (backend ready);
#27 closes it. Documented, not silently half-built.

## Approach

Add an **`agent_agui`** fragment to the `agent` feature serving the AG-UI SSE run endpoint, reusing the
existing pydantic-ai agent build + `tool_registry`. Gated by `agent.llm` (the AGUIAdapter needs a
pydantic-ai agent), so it's opt-in.

1. **Endpoint** — `endpoints/agui.py`: `POST /agent` (SSE). Bind the body to an `AgentRequest(RunAgentInput)`
   subclass (only `thread_id`/`run_id`/`messages` required; defaults for `state`/`tools`/`context`/
   `forwarded_props`) — platform's pattern. Build the agent via the reusable `build_agent()` (extracted
   from `llm_runner._build_agent`), register `tool_registry` tools, then use the **manual adapter path**
   (NOT `dispatch_request`, which re-reads the body and conflicts with FastAPI body binding):
   `adapter = AGUIAdapter(agent=agent, run_input=req)`;
   `return adapter.streaming_response(adapter.run_stream(...), accept=request.headers.get("accept"))`.
   Confirm the exact 1.74 surface during impl. `EventEncoder.get_content_type()` → `text/event-stream`.
2. **Mount** — `/api/v1/agent` (inject include prefix `/agent`; `api_router` is already at `/api/v1`).
   Set the Vue template's `VITE_AGENT_BASE_URL` to the real endpoint (derive in `vue_context` /
   `.env.jinja` → `{{ env_api_base_url }}/api/v1/agent` or `http://localhost:8000/api/v1/agent`). The
   frontend uses the env value as the FULL url. Verify no trailing-slash POST redirect + Vite proxy
   covers `/api/v1/agent`.
3. **pydantic-ai bump** — replace `pydantic-ai>=0.0.14` with a 1.x line that ships `pydantic_ai.ui.ag_ui`
   **and** provider SDKs. `pydantic-ai-slim[ag-ui]` alone omits providers, so use e.g.
   `pydantic-ai-slim[ag-ui,anthropic,openai,google]>=1.74,<2` (or full `pydantic-ai>=1.74` if it bundles
   `ui.ag_ui` — verify). The **WS `llm_runner` MUST be migrated to the same version** (one pyproject = one
   pydantic-ai; the keep-WS-on-0.0.14 fallback is infeasible). codex audited 1.74: `Agent(...)`,
   `agent.iter/run/tool_plain`, `pydantic_ai.messages.{FunctionToolCallEvent,PartDeltaEvent,
   FunctionToolResultEvent,TextPartDelta}`, `models.{anthropic.AnthropicModel,openai.OpenAIChatModel,
   google.GoogleModel}`, `providers.openrouter.OpenRouterProvider` all still exist — so the migration is
   expected to be small (smoke + patch any moved symbol).
4. **WS endpoint** — KEEP it (legacy/raw transport); **SSE is the canonical transport for the generated
   frontend** (document this — that's the "unify"). No WS rip-out this tranche.
5. **Tools** — register the same `tool_registry` server-side tools onto the agent. Frontend/deferred tools
   in `RunAgentInput.tools` become an `ExternalToolset` automatically (the run ends with the tool call →
   frontend can render it). NB: server-side tool *results* emit upstream `TOOL_CALL_RESULT`, which
   canvas-core currently treats as UNKNOWN (no-op) — fine for status-only UI; result *display* is a #27
   concern. `THINKING_*` events likewise parse as UNKNOWN (harmless).
6. **Auth** — **gate the endpoint with the auth dependency when auth is enabled** (it spends LLM budget +
   invokes server-side tools — same posture as the already-gated `/api/v1/tools`, NOT the ungated echo WS).
   In a no-auth/dev project it stays open. Document rate/cost/body-size limits + cancellation as hardening.
7. **Fragment wiring** — `agent_agui` `depends_on=("agent_streaming","agent")` (reuses `agents/` +
   `tool_registry` + the pydantic-ai `build_agent`). `inject.yaml` mounts the router. Enabled by `agent.llm`
   (no new option; AG-UI needs the pydantic-ai agent that `agent.llm` provides). **Known gap (document):**
   an `include_chat` project WITHOUT `agent.llm` renders a chat UI with no SSE backend — pre-existing
   (real responses always needed `agent.llm`); out of scope here, noted in the agent README/HARDENING.

## Critical files

- ADD `agent_agui/python/files/src/app/api/v1/endpoints/agui.py` — the SSE endpoint (manual adapter path).
- ADD `agent_agui/python/files/src/app/agents/agui_models.py` — `AgentRequest(RunAgentInput)` (defaults for state/tools/context/forwarded_props).
- ADD `agent_agui/python/inject.yaml` — router import + mount at prefix `/agent` (→ `/api/v1/agent`).
- ADD `agent_agui/python/files/src/app/agents/AGENT_AGUI_HARDENING.md` (or a README section) — auth/cost/persistence/cancellation/deferred-tool gaps.
- EDIT `agent/python/files/src/app/agents/llm_runner.py` — expose a reusable `build_agent()`; **migrate the imports/loop to pydantic-ai 1.74** (audit each symbol).
- EDIT `forge/features/agent/fragments.py` — register `agent_agui`; bump pydantic-ai dep + `[ag-ui]` + provider extras.
- EDIT `forge/features/agent/options.py` — `agent.llm` (and/or `agent.streaming`) `enables` `agent_agui`.
- EDIT `forge/variable_mapper.py` (`vue_context`) and/or `.env.jinja` — `VITE_AGENT_BASE_URL` → `/api/v1/agent`.
- TEST `tests/test_features_agent_agui.py` — resolution + render + endpoint mounts at `/api/v1/agent` + pyproject has the exact bumped dep string (incl. provider extras) + the WS endpoint still renders.
- TEST wire-compat fixture — capture a real `EventEncoder().encode(...)` frame for each of RUN_STARTED / TEXT_MESSAGE_{START,CONTENT,END} / TOOL_CALL_{START,ARGS,END} / RUN_FINISHED / RUN_ERROR and assert canvas-core's `KNOWN_TYPES` + the field names it reads cover them (Python-side structural assertion against `events.ts`). Note `TOOL_CALL_RESULT`/`THINKING_*` are intentionally UNKNOWN.
- GOLDEN: regenerate **`full_feature` AND `full_feature_max`** — `full_feature` (chat, no agent) changes only by the `.env` `VITE_AGENT_BASE_URL` line; `full_feature_max` (agent on) changes by the new endpoint + pyproject bump. The other 4 stay byte-identical. Both diffs are the audit.

## Verification

1. **Fragment/unit** — `agent_agui` resolves (python-only); renders endpoint + inject + AgentRequest; pyproject has the exact dep string (with provider extras); WS endpoint still present.
2. **WS-runner migration smoke** — after the bump, import `llm_runner` + exercise its construction under the *generated* dependency set (provider extras present), in the py3.13 container. This is the bump-risk gate.
3. **Wire-compat** — the `EventEncoder` regression fixture (real encode) ⊆ canvas-core `KNOWN_TYPES` + parsed fields.
4. **Golden** — `full_feature` (+`.env` line) and `full_feature_max` (+endpoint+dep) regen reviewed; other 4 byte-identical.
5. **e2e (docker, opt-in)** — generate `agent.llm` + Vue, boot, drive the real `useAgentClient` against `/api/v1/agent` (covers VITE_AGENT_BASE_URL, CORS/proxy, Authorization, trailing slash): assert the stream starts `data: {"type":"RUN_STARTED"}` and the UI renders streamed text. Skipped on the constrained dev box.
6. **arm64 + py3.13** — docker-smoke the pydantic-ai 1.x bump in the container (runtime, not just host).
7. **disconnect/timeout** — a smoke that client disconnect stops the run (base `StreamingResponse` behavior; add disconnect polling / `ModelSettings.timeout` if needed, per platform's wrapper).

## Risks / decisions (resolved in review)

- **R1 — pydantic-ai bump migrates the WS runner (no two-version fallback).** Pin 1.74-line; codex audit
  says the WS runner's symbols still exist → small migration; smoke under the generated deps. Provider
  extras are a hidden dep — include them explicitly.
- **R2 — keep WS; SSE canonical for the generated frontend** (documented).
- **R3 — gate via `agent.llm`** (AG-UI needs the pydantic-ai agent). `include_chat`-without-`agent.llm`
  chat-with-no-backend is pre-existing + documented, not solved here.
- **R4 — `.env` change affects `full_feature` + `full_feature_max` goldens** (both regen, intentional).
- **R5 — manual adapter path** (`run_stream` + `streaming_response`), not `dispatch_request` (body conflict).
- **R6 — deferred-tool RESUME deferred to #27** (frontend must persist `toolCalls`/`tool` messages).
- **R7 — auth-gated when auth enabled**; rate/cost/body/cancellation documented as hardening.
- **R8/R9 — persistence (threadId→conversation repo) + reconnect + cancellation/buffering**: deferred +
  documented; this tranche is first-run streaming, not a full resume/persistence story.

<!-- codex-review-status: finalized -->
