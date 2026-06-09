# Unify the generated agent backend on the AG-UI SSE protocol

## Context

forge's generated agentic chat has a **protocol split-brain** (a verified prod-readiness gap):

- The generated **frontend** (`useAgentClient` on the vendored `canvas-core`) POSTs `RunAgentInput`
  (`{threadId, runId, messages, state, tools, context, forwardedProps}`) to `VITE_AGENT_BASE_URL`
  and consumes **AG-UI SSE**: single-channel `data: {json}\n\n` frames whose `type` is a
  SCREAMING_CASE string (`RUN_STARTED`, `TEXT_MESSAGE_START/CONTENT/END`, `TOOL_CALL_START/ARGS/END`,
  `STATE_SNAPSHOT/DELTA`, `CUSTOM`, `ACTIVITY_SNAPSHOT`, `RUN_FINISHED`, `RUN_ERROR`) and whose fields
  are camelCase (`messageId`, `toolCallId`, `toolCallName`, `delta`, `snapshot`). The `event:` line is
  ignored; the type lives inside the JSON.
- The generated **backend** (`agent` feature, `agent_streaming` fragment) serves a **WebSocket** at
  `/api/v1/ws/agent` emitting a *different*, snake_case `AgentEvent` union (`text_delta`, `tool_call`,
  `agent_status`, …). **Nothing serves the SSE endpoint the frontend calls.** The WS endpoint has no
  generated consumer.

So the agentic chat does not work end-to-end, and the deferred frontend-tool loop (#27) can't round-trip.

**Decisive discovery:** platform's AG-UI SSE backend is almost entirely **upstream libraries** —
`pydantic-ai-slim[ag-ui]` (`pydantic_ai.ui.ag_ui.AGUIAdapter` / `AGUIEventStream`) + `ag-ui-protocol`
(`ag_ui.core` models + `ag_ui.encoder.EventEncoder`, which frames `data: <model_dump_json(by_alias=True,
exclude_none=True)>\n\n`). `by_alias=True` yields SCREAMING_CASE `type` + camelCase fields — **exactly
what forge's canvas-core parser reads.** And **forge already uses pydantic-ai** for its agent runner.

So "unify on AG-UI SSE" is not a from-scratch protocol implementation: it is **add an AG-UI SSE
endpoint that hands forge's existing pydantic-ai agent to `AGUIAdapter.dispatch_request`**, and the
exact wire the frontend expects falls out of the upstream encoder. The deferred-tool loop (#27) then
comes essentially free: `AGUIAdapter` turns `RunAgentInput.tools` into a pydantic-ai `ExternalToolset`,
ends the run with `DeferredToolRequests` when the LLM calls one (emitting `TOOL_CALL_*` + `RUN_FINISHED`),
and resumes on the follow-up run because `AGUIAdapter.load_messages` rebuilds the tool result from history.

## Approach

Add an **`agent_agui`** fragment to the `agent` feature that serves the AG-UI SSE run endpoint, reusing
the existing pydantic-ai agent build + tool registry. Keep changes opt-in (agent is already gated).

1. **Endpoint** — `endpoints/agui.py`: `POST /agent` (SSE). Bind the body to a subclass of
   `ag_ui.core.RunAgentInput` (defaulting `state`/`tools`/`context`/`forwardedProps`). Build the agent
   via the existing `llm_runner` agent construction (extract `_build_agent()` into a reusable
   `build_agent()` the AG-UI endpoint and the WS runner both call), then:
   `adapter = AGUIAdapter(agent=agent, run_input=run_input); return adapter.streaming_response(accept)`
   (or the upstream `AGUIAdapter.dispatch_request(request, agent=agent)` convenience). The adapter emits
   the AG-UI SSE stream natively; we write **no** event-translation code.
2. **Mount path** — the frontend calls `VITE_AGENT_BASE_URL`. Mount the endpoint at `/api/v1/agent`
   (consistent with every other route) and set the Vue template's `VITE_AGENT_BASE_URL` default to
   `${VITE_API_BASE_URL}/api/v1/agent` (or `http://localhost:8000/api/v1/agent` in `.env.jinja`). Confirm
   `useAgentClient` uses the env value as the full URL (it does: `VITE_AGENT_BASE_URL || origin+'/agent/'`).
3. **pydantic-ai version** — bump the `agent` fragment dep from `pydantic-ai>=0.0.14` to a 1.x line that
   ships `pydantic_ai.ui.ag_ui` **and** still supports the WS `llm_runner`'s `agent.iter()` /
   `pydantic_ai.messages.*` / model classes (platform uses `pydantic-ai-slim==1.74.0`). Add the
   `[ag-ui]` extra (pulls `ag-ui-protocol`). **This is the primary risk** — see Risks.
4. **WS endpoint** — KEEP `agent_streaming`'s WS endpoint for now (it's harmless, some consumers may use
   raw WS); the AG-UI SSE endpoint is the canonical transport the generated frontend uses. Do NOT rip out
   the WS path in this tranche (smaller blast radius, fewer test rewrites). A later tranche can deprecate it.
5. **Tools** — the AG-UI endpoint registers the same `tool_registry` server-side tools onto the agent
   (reuse `_register_tool`). Frontend/deferred tools arrive in `RunAgentInput.tools` and are handled by
   `AGUIAdapter`'s `ExternalToolset` automatically; no extra wiring here. (Populating the frontend's
   `tools: []` with a generic toolset is the separate #27 follow-on, out of scope for THIS tranche —
   this tranche makes the *backend* speak AG-UI so the chat + any future toolset work end to end.)
6. **Auth** — match the existing WS endpoint posture (ungated by default; the frontend sends `Authorization:
   Bearer` only when a token getter is configured). The endpoint reads the bearer if present (for a future
   auth-bearing UnitOfWork / persistence) but does not require it, mirroring `/ws/agent`.
7. **Fragment wiring** — `agent_agui` `depends_on=("agent_streaming",)` (reuses `agents/` package +
   `tool_registry`) and pulls the pydantic-ai agent build (depends on the `agent` fragment / `agent.llm`).
   `inject.yaml` mounts the router at `/api/v1/agent` and (if needed) installs default tools at
   `FORGE:LIFECYCLE_STARTUP`. Gate behind a new option `agent.agui` (default off) OR fold into
   `agent.llm` — decide in review (leaning: fold into `agent.llm` since AG-UI needs the pydantic-ai agent
   anyway, so an LLM-backed agent implies the AG-UI transport is the useful one).

## Critical files

- ADD `forge/features/agent/templates/agent_agui/python/files/src/app/api/v1/endpoints/agui.py` — the SSE endpoint.
- ADD `.../agent_agui/python/files/src/app/agents/agui_models.py` — `RunAgentInput` subclass (if not importing ag_ui.core directly).
- ADD `.../agent_agui/python/inject.yaml` — router import + mount at `/api/v1/agent`.
- EDIT `forge/features/agent/templates/agent/python/files/src/app/agents/llm_runner.py` — extract a reusable `build_agent()` (currently `_build_agent()`), used by both the WS runner and the AG-UI endpoint.
- EDIT `forge/features/agent/fragments.py` — register `agent_agui`; bump pydantic-ai dep + add `[ag-ui]` extra.
- EDIT `forge/features/agent/options.py` — `agent.agui` option (or fold into `agent.llm`) → enables `agent_agui`.
- EDIT `forge/templates/apps/vue-frontend-template/template/.env.jinja` — `VITE_AGENT_BASE_URL` default → the `/api/v1/agent` URL.
- TEST `tests/test_features_agent_agui.py` — fragment resolution + render + the endpoint mounts at /api/v1/agent + pyproject has `pydantic-ai-slim[ag-ui]`.
- TEST a wire-compat check: feed a sample `AGUIAdapter`/`EventEncoder` SSE frame through forge's `canvas-core` `parseEvent`/`reduce` (TS) OR assert the emitted `type`+field names match canvas-core's `KNOWN_TYPES` + field reads (a Python-side structural assertion against the contract).
- GOLDEN: regenerate `tests/golden/snapshots/full_feature_max.json` (it enables agent → it WILL change: new endpoint file + pyproject dep bump). The other 5 goldens stay byte-identical (they don't enable agent). The full_feature_max diff is the audit.

## Verification

1. **Unit/fragment** — `agent_agui` resolves (python-only), renders the endpoint + inject, pyproject gains `pydantic-ai-slim[ag-ui]` at the bumped version.
2. **Wire-compat** — the emitted AG-UI event `type` strings + field names match what `canvas-core` `events.ts` `KNOWN_TYPES` + `parseEvent` read (RUN_STARTED/TEXT_MESSAGE_*/TOOL_CALL_*/RUN_FINISHED/RUN_ERROR; camelCase messageId/toolCallId/toolCallName). Ideally render a project + run the canvas-core vitest against a captured `EventEncoder` frame.
3. **Golden** — only `full_feature_max` changes; review the diff (new agui endpoint + pydantic-ai bump); the other 5 byte-identical.
4. **WS llm_runner still works** — after the pydantic-ai bump, the existing WS path imports + the agent.iter()/run() loop still resolve (smoke the import + a unit of the runner). This is the bump-risk gate.
5. **e2e (docker, opt-in)** — generate a project with `agent.llm` + a Vue frontend, boot it, POST a `RunAgentInput` to `/api/v1/agent`, assert the SSE stream begins `data: {"type":"RUN_STARTED"}` and the frontend canvas-core can parse it. (Heavy; runs on a Docker host, skipped on the constrained dev box like the other e2e.)
6. **arm64 + py3.13** — docker-smoke the pydantic-ai 1.x bump in the container (the runtime, not just host).

## Risks / open questions (for review)

- **R1 (primary): the pydantic-ai 0.0.14 → 1.x bump may break the existing WS `llm_runner`.** Its API
  surface (`Agent(model, system_prompt)`, `agent.tool_plain`, `agent.iter()`, `agent.run()`,
  `pydantic_ai.messages.{FunctionToolCallEvent, PartDeltaEvent, FunctionToolResultEvent, TextPartDelta}`,
  `pydantic_ai.models.{anthropic.AnthropicModel, openai.OpenAIChatModel, google.GoogleModel}`,
  `providers.openrouter.OpenRouterProvider`) was written for 0.0.14. Some of these renamed across the
  1.0 boundary (e.g. model class names, event types). **Mitigation:** pin to platform's exact line
  (`pydantic-ai-slim==1.74.0`), audit each llm_runner import against 1.74, and patch the WS runner where
  the API moved. If the WS runner is too entangled to fix cheaply, fall back to: the AG-UI endpoint uses
  its own minimal agent build (it does NOT need the WS runner's manual streaming — `AGUIAdapter` streams),
  and the WS `llm_runner` is left on its current API by pinning only the AG-UI endpoint's import path.
  Decide in review.
- **R2: replace vs keep the WS endpoint.** Plan keeps both. Is that the right "unify"? Or should WS be
  removed (frontend never uses it)? Keeping is lower-risk; removing is cleaner. Lean keep-for-now.
- **R3: option shape** — new `agent.agui` (off by default) vs folding into `agent.llm`. Folding makes the
  AG-UI transport the default for LLM agents (the useful default) but changes `full_feature_max` more.
- **R4: mount path + env** — `/api/v1/agent` + `VITE_AGENT_BASE_URL` alignment. Confirm the frontend uses
  the env var as the full endpoint URL (no extra `/agent/` suffix appended when the env is set).
- **R5: streaming_response API** — confirm the exact `pydantic_ai.ui.ag_ui` surface in 1.74
  (`AGUIAdapter.dispatch_request` vs `adapter.run_stream` + `adapter.streaming_response`) and the Starlette
  `StreamingResponse` content-type. Verify against the installed 1.74 in platform's venv.

<!-- codex-review-status: pending -->
