"""``agent.mode`` — discriminated-union layer mode for the agentic stack.

Theme 2A promotes ``agent.mode`` from the Phase C placeholder
(``forge/features/agent/options.py``'s old registration) into a real
layer discriminator, sharing the registration *shape* with
``backend.mode`` / ``frontend.mode`` / ``database.mode`` but actively
mapping each enum value to a bundle of conversational-AI fragments.

Layout:

* ``none``         — empty bundle, matching the other layer modes' "no
  fragment fanout for the ``none`` case" invariant.
* ``llm_only``     — LLM provider port + chat history. Enough to host
  ``LlmProviderPort`` behind a Dishka adapter and persist conversation
  rows. No tool registry, no MCP scaffolds, no agent runner. Matches
  the "I just want to call an LLM and keep transcripts" footprint.
* ``tool_calling`` — full agent loop: streaming WebSocket, tool
  registry, agent runner, plus the MCP consumer-side router + Vue
  scaffolds. Picks up everything the chat-product wants.
* ``multi_agent``  — registered placeholder for the v2 agent-to-agent
  routing layer. Fragment wiring is deferred; ``ProjectConfig.validate``
  raises a clear "not yet implemented" so users discover the gap at
  config-load time rather than mid-generate.

Backwards compatibility: the existing ``agent.streaming`` /
``agent.tools`` / ``agent.llm`` flags continue to work — they remain
the fine-grained surface, and ``agent.mode`` is an additional fast-path
preset that fans out to overlapping fragments. The resolver de-dupes
fragment names, so combining a flag with a mode that already enables
it is a no-op rather than an error.

Cross-layer rule: ``agent.mode != "none"`` requires
``backend.mode != "none"`` — the agent loop needs a backend to live in.
Enforced in :meth:`ProjectConfig._validate_agent_mode`.
"""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

# Fragment bundles per agent.mode value. Centralised here so the
# capability resolver, the cross-layer validator, and the Theme 2A test
# suite all read the same source of truth.
#
# ``llm_only`` ships ``llm_port`` (the abstract LlmProviderPort) plus
# ``conversation_persistence`` (Conversation / Message / ToolCall
# SQLAlchemy models + repo + Alembic migration). The user still picks a
# concrete provider adapter via ``llm.provider``; the mode preset only
# carries the provider-agnostic foundation.
#
# ``tool_calling`` layers the full agent triple on top — agent_streaming
# (WebSocket endpoint), agent_tools (tool registry + pre-baked tools),
# agent (pydantic-ai loop) — plus mcp_server + mcp_ui (the MCP consumer
# side: /mcp/tools + /mcp/invoke + Vue ToolRegistry + ApprovalDialog).
# Transitive deps (e.g. agent → agent_streaming, agent_tools) come in
# automatically via Fragment.depends_on, but listing them here keeps
# the bundle reviewable without chasing depends_on chains.
#
# ``multi_agent`` is intentionally empty — the option accepts the value
# so users can register intent in forge.toml today, but
# _validate_agent_mode raises before any generation runs.
_AGENT_MODE_ENABLES: dict[str, tuple[str, ...]] = {
    "none": (),
    "llm_only": ("llm_port", "conversation_persistence"),
    "tool_calling": (
        "llm_port",
        "conversation_persistence",
        "agent_streaming",
        "agent_tools",
        "agent",
        "mcp_server",
        "mcp_ui",
    ),
    "multi_agent": (),
}


register_option(
    Option(
        path="agent.mode",
        type=OptionType.ENUM,
        default="none",
        options=("none", "llm_only", "tool_calling", "multi_agent"),
        # ENUM values "llm_only" / "tool_calling" both pull
        # ``conversation_persistence`` (DB-backed). "none" / "multi_agent"
        # are no-ops at the persistence layer but the option-level flag
        # is the lever the walker checks; for ENUMs the validator
        # narrows further via the DB-conflict collector. Init #7
        # follow-up — codex flagged this gap.
        requires_database=True,
        summary="Layer discriminator for the agentic/LLM stack.",
        description="""\
Fast-path preset for the conversational-AI surface. Mirrors
``backend.mode`` / ``frontend.mode`` / ``database.mode`` in shape:
ENUM with ``none`` as a no-op default, other values fanning out to a
fragment bundle.

OPTIONS:
  - none         No agent stack. Default.
  - llm_only     LlmProviderPort + chat-history persistence. Pair with
                 ``llm.provider`` to pick a concrete adapter
                 (openai / anthropic / ollama / bedrock). No tool
                 registry, no agent runner — for services that just
                 want to call an LLM and keep transcripts.
  - tool_calling Full agent loop: streaming WebSocket, tool registry,
                 pydantic-ai runner, MCP consumer router + Vue UI.
                 The "chat product" preset.
  - multi_agent  Reserved for v2 agent-to-agent routing. Accepted as a
                 value today, but generation raises NOT_IMPLEMENTED at
                 ``ProjectConfig.validate()`` — register the intent in
                 ``forge.toml`` and the upgrade path stays clean.

Backwards compatibility: ``agent.streaming`` / ``agent.tools`` /
``agent.llm`` / ``conversation.persistence`` / ``platform.mcp``
remain the fine-grained surface. ``agent.mode`` is an *additional*
preset — picking both a mode and a flag that enable the same fragment
is a no-op (the resolver de-dupes by fragment name).

CROSS-LAYER RULE: ``agent.mode != "none"`` requires
``backend.mode != "none"``. The agent loop lives in a backend
service; ``backend.mode=none`` (frontend-only project) plus a non-none
agent.mode is rejected at validate time.""",
        category=FeatureCategory.CONVERSATIONAL_AI,
        stability="experimental",
        enables=_AGENT_MODE_ENABLES,
    )
)


__all__ = ["_AGENT_MODE_ENABLES"]
