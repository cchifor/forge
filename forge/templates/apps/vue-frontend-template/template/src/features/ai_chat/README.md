# ai_chat — agentic chat UI

A streaming chat surface built on the AG-UI protocol: `useAgentClient`
(in `composables/`) POSTs an AG-UI `RunAgentInput` to `VITE_AGENT_BASE_URL`
and renders the **AG-UI Server-Sent Events** stream the backend replies with
(text deltas, tool-call status, generative-UI "canvas" activities).

## Requires an AG-UI SSE backend

The chat only works against a backend that serves the AG-UI SSE run endpoint at
**`POST /api/v1/agent`**. In forge that endpoint is shipped by the `agent_agui`
fragment, which is enabled by **`agent.llm`**.

**If this project was generated with a chat frontend but WITHOUT `agent.llm`,
there is no AG-UI backend** — `useAgentClient` will POST to a route that returns
404 and the chat will not respond. To wire it up, regenerate (or add the
fragment) with `agent.llm` enabled (which also pulls `agent.streaming` +
`agent.tools`). The legacy `/api/v1/ws/agent` WebSocket is a separate raw
transport this UI does not use.

## Agent endpoint URL

`VITE_AGENT_BASE_URL` defaults to a relative `/api/<backend>/v1/agent`, so the
browser reaches the endpoint through the same origin + Vite proxy as every other
API call (dev) or same-origin (prod). Override it in `.env` to point at an
external agent service.
