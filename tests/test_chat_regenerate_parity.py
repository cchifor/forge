"""Cross-stack parity for chat message regeneration (Pillar G.3).

The Vue, Svelte, and Flutter frontend templates each ship a chat
client. Pillar G.3 adds ``regenerate(messageId)`` to all three so a
user can ask the agent for a fresh take on the last response WITHOUT
losing the thread (distinct from ``editAndResend``, which mints a
new thread).

This module pins the contract that's load-bearing across stacks:

* the API surface (function exists, takes a single ``messageId`` arg);
* the threadId-preservation invariant — ``regenerate`` MUST re-use the
  current thread, unlike ``editAndResend`` which creates a new one;
* the no-op guards (unknown id, run-in-flight);
* the wiring through the public re-export points so consumers don't
  have to reach into agent-client internals;
* the UI button is present in the message-list widget.

These are static text-asserts against the template tree — no copier
run needed, matching the rest of the chat invariant suite (see
``tests/test_flutter_ag_ui_client_deprecated.py``).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-stack file paths — pinned here so a template move surfaces as a
# loud "file not found" before any of the assertions silently pass.
_VUE_AGENT_CLIENT = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src"
    / "features/ai_chat/composables/useAgentClient.ts"
)
_VUE_USE_CHAT = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src"
    / "features/ai_chat/composables/useAiChat.ts"
)
_VUE_CHAT_UI = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src"
    / "features/ai_chat/ui/AiChat.vue"
)
_VUE_MESSAGE_UI = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src"
    / "features/ai_chat/ui/AiChatMessage.vue"
)

_SVELTE_AGENT_CLIENT = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src"
    / "lib/features/chat/model/agent-client.svelte.ts"
)
_SVELTE_CHAT_STORE = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src"
    / "lib/features/chat/model/chat.svelte.ts"
)
_SVELTE_CHAT_UI = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src"
    / "lib/features/chat/ui/AiChat.svelte"
)
_SVELTE_MESSAGE_UI = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src"
    / "lib/features/chat/ui/AiChatMessage.svelte"
)

_FLUTTER_PROVIDERS = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}"
    / "lib/src/features/chat/presentation/chat_providers.dart"
)
_FLUTTER_MESSAGE_LIST = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}"
    / "lib/src/features/chat/presentation/chat_message_list.dart"
)


# ---------------------------------------------------------------------------
# Surface — `regenerate(messageId)` exists in all three reducers
# ---------------------------------------------------------------------------


class TestRegenerateSurface:
    """Each stack exposes ``regenerate`` with a single ``messageId`` arg."""

    def test_vue_agent_client_defines_regenerate(self) -> None:
        body = _VUE_AGENT_CLIENT.read_text()
        assert "function regenerate(messageId: string)" in body, (
            "Vue useAgentClient must define `regenerate(messageId: string)`"
        )

    def test_svelte_agent_client_defines_regenerate(self) -> None:
        body = _SVELTE_AGENT_CLIENT.read_text()
        assert "function regenerate(messageId: string)" in body, (
            "Svelte agent-client must define `regenerate(messageId: string)`"
        )

    def test_flutter_chat_notifier_defines_regenerate(self) -> None:
        body = _FLUTTER_PROVIDERS.read_text()
        assert "Future<void> regenerate(String messageId)" in body, (
            "Flutter ChatNotifier must define "
            "`Future<void> regenerate(String messageId)`"
        )


# ---------------------------------------------------------------------------
# Re-exports — consumers shouldn't have to reach into the agent client
# ---------------------------------------------------------------------------


class TestRegenerateReExports:
    """Public stores/composables surface ``regenerate`` for UI code."""

    def test_vue_use_ai_chat_re_exports_regenerate(self) -> None:
        body = _VUE_USE_CHAT.read_text()
        # Defined locally as a wrapper that calls into the agent client.
        assert "function regenerate(messageId: string)" in body, (
            "useAiChat() must define a `regenerate` wrapper"
        )
        # AND it must appear in the returned surface (the destructuring
        # target in AiChat.vue).
        assert "regenerate," in body, (
            "useAiChat() must include `regenerate` in its return object"
        )

    def test_svelte_chat_store_re_exports_regenerate(self) -> None:
        body = _SVELTE_CHAT_STORE.read_text()
        assert "regenerate: agent.regenerate" in body, (
            "getChatStore() must re-export `regenerate` from the agent client"
        )


# ---------------------------------------------------------------------------
# Load-bearing invariant — regenerate KEEPS the thread
# ---------------------------------------------------------------------------


class TestThreadIdPreservation:
    """
    The whole point of ``regenerate`` is that conversational context
    survives the call. If a future refactor accidentally adds a
    ``= crypto.randomUUID()`` (or a ``_threadId = _newId()``) inside
    ``regenerate``, these tests catch it before merge.
    """

    def test_vue_regenerate_does_not_mint_new_thread(self) -> None:
        body = _VUE_AGENT_CLIENT.read_text()
        regen_block = _extract_block(body, "function regenerate(messageId: string)")
        assert "currentThreadId = " not in regen_block, (
            "Vue regenerate() must NOT reassign currentThreadId — "
            "that breaks the conversation context invariant. Found:\n"
            f"{regen_block}"
        )
        assert "randomUUID" not in regen_block, (
            "Vue regenerate() must NOT mint a new UUID — "
            "that breaks the conversation context invariant."
        )

    def test_svelte_regenerate_does_not_mint_new_thread(self) -> None:
        body = _SVELTE_AGENT_CLIENT.read_text()
        regen_block = _extract_block(body, "function regenerate(messageId: string)")
        assert "currentThreadId = " not in regen_block, (
            "Svelte regenerate() must NOT reassign currentThreadId. Found:\n"
            f"{regen_block}"
        )
        assert "randomUUID" not in regen_block, (
            "Svelte regenerate() must NOT mint a new UUID."
        )

    def test_flutter_regenerate_does_not_mint_new_thread(self) -> None:
        body = _FLUTTER_PROVIDERS.read_text()
        regen_block = _extract_block(
            body, "Future<void> regenerate(String messageId)"
        )
        assert "_threadId = " not in regen_block, (
            "Flutter regenerate() must NOT reassign _threadId. Found:\n"
            f"{regen_block}"
        )
        assert "_newId()" not in regen_block.split("await _runAgent")[0], (
            "Flutter regenerate() must NOT mint a new threadId via _newId() "
            "before the _runAgent call."
        )


# ---------------------------------------------------------------------------
# Re-uses lastRunOptions snapshot (so attachments survive regen)
# ---------------------------------------------------------------------------


class TestLastRunOptionsReuse:
    """
    Pillar G.5 introduced ``lastRunOptions`` so RUN_ERROR retry could
    replay the failed request. Pillar G.3 piggy-backs on the same
    snapshot: a regenerate after attachments must NOT silently lose
    them. Asserts each stack's regenerate threads its run through the
    stored snapshot instead of an empty options object.
    """

    def test_vue_regenerate_passes_lastRunOptions(self) -> None:
        body = _VUE_AGENT_CLIENT.read_text()
        regen_block = _extract_block(body, "function regenerate(messageId: string)")
        assert "runAgent(lastRunOptions)" in regen_block, (
            "Vue regenerate() must forward `lastRunOptions` to runAgent"
        )

    def test_svelte_regenerate_passes_lastRunOptions(self) -> None:
        body = _SVELTE_AGENT_CLIENT.read_text()
        regen_block = _extract_block(body, "function regenerate(messageId: string)")
        assert "runAgent(lastRunOptions)" in regen_block, (
            "Svelte regenerate() must forward `lastRunOptions` to runAgent"
        )

    def test_flutter_regenerate_passes_lastForwardedProps(self) -> None:
        body = _FLUTTER_PROVIDERS.read_text()
        regen_block = _extract_block(
            body, "Future<void> regenerate(String messageId)"
        )
        assert "_lastForwardedProps" in regen_block, (
            "Flutter regenerate() must forward `_lastForwardedProps`"
        )
        assert "_lastBearerToken" in regen_block, (
            "Flutter regenerate() must forward `_lastBearerToken`"
        )


# ---------------------------------------------------------------------------
# Anti-double-click guard — regenerate is a no-op while a run is in flight
# ---------------------------------------------------------------------------


class TestRunInFlightGuard:
    """Spamming Regenerate during a slow run must not queue multiple runs."""

    def test_vue_regenerate_guards_on_isRunning(self) -> None:
        body = _VUE_AGENT_CLIENT.read_text()
        regen_block = _extract_block(body, "function regenerate(messageId: string)")
        assert "isRunning.value" in regen_block and "return" in regen_block, (
            "Vue regenerate() must short-circuit when isRunning.value is true"
        )

    def test_svelte_regenerate_guards_on_isRunning(self) -> None:
        body = _SVELTE_AGENT_CLIENT.read_text()
        regen_block = _extract_block(body, "function regenerate(messageId: string)")
        # Codex Phase B round 1 follow-up tightened the guard to
        # `if (!hasRun || isRunning) return` (matching retryLastRun).
        # Accept the multi-clause shape OR the original isolated check.
        assert (
            "isRunning" in regen_block and "return" in regen_block
        ), "Svelte regenerate() must short-circuit when isRunning is true"

    def test_flutter_regenerate_guards_on_isRunning(self) -> None:
        body = _FLUTTER_PROVIDERS.read_text()
        regen_block = _extract_block(
            body, "Future<void> regenerate(String messageId)"
        )
        assert "state.isRunning" in regen_block, (
            "Flutter regenerate() must short-circuit when state.isRunning is true"
        )


# ---------------------------------------------------------------------------
# UI surface — the Regenerate button is wired in the message list
# ---------------------------------------------------------------------------


class TestRegenerateUiWired:
    """Each stack ships a UI affordance that calls into ``regenerate``."""

    def test_vue_ui_wires_regenerate_button(self) -> None:
        # The parent AiChat.vue destructures `regenerate` and forwards
        # to the child via an emit; the child renders the button.
        chat_body = _VUE_CHAT_UI.read_text()
        msg_body = _VUE_MESSAGE_UI.read_text()
        assert "regenerate," in chat_body, "AiChat.vue must destructure `regenerate`"
        assert '@regenerate=' in chat_body, (
            "AiChat.vue must listen for the @regenerate event from AiChatMessage"
        )
        assert "aria-label=\"Regenerate response\"" in msg_body, (
            "AiChatMessage.vue must render a Regenerate button"
        )

    def test_svelte_ui_wires_regenerate_button(self) -> None:
        chat_body = _SVELTE_CHAT_UI.read_text()
        msg_body = _SVELTE_MESSAGE_UI.read_text()
        assert "chat.regenerate" in chat_body, (
            "AiChat.svelte must pass `chat.regenerate` to AiChatMessage"
        )
        assert "onRegenerate" in msg_body, (
            "AiChatMessage.svelte must accept an `onRegenerate` callback"
        )
        assert 'aria-label="Regenerate response"' in msg_body, (
            "AiChatMessage.svelte must render a Regenerate button"
        )

    def test_flutter_ui_wires_regenerate_button(self) -> None:
        body = _FLUTTER_MESSAGE_LIST.read_text()
        assert ".regenerate(messages[i].id)" in body, (
            "chat_message_list.dart must call notifier.regenerate(...)"
        )
        assert "Regenerate" in body, (
            "chat_message_list.dart must render a Regenerate label"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_block(source: str, signature: str) -> str:
    """Return the body of the function whose declaration line contains
    ``signature``. Brace-matches from the first ``{`` after the signature
    until the matching close — handles nested blocks. Used by the
    invariant asserts above so a regression in ``regenerate`` doesn't
    silently pass because the offending string lives elsewhere in the
    file (e.g. inside ``editAndResend`` or ``runAgent``).
    """
    start = source.find(signature)
    assert start != -1, f"signature not found: {signature!r}"
    brace_open = source.find("{", start)
    assert brace_open != -1, f"no opening brace after signature: {signature!r}"
    depth = 0
    for i in range(brace_open, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace_open : i + 1]
    raise AssertionError(f"unbalanced braces after signature: {signature!r}")
