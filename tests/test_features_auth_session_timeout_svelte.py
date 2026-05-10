"""Invariants for the Svelte session-timeout fragment (Phase 8).

Mirrors ``test_features_auth_session_timeout_vue.py`` — same RFC
constraints, ported to Svelte 5's runes idioms ($state / $derived /
$effect). Cross-language parity with the Vue fragment is enforced by
both files asserting the same load-bearing semantics: drift-immune
countdown, BroadcastChannel cross-tab dedup, visibility gating, 30-
second debounce, silent disable on 401 / timeouts=0.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


def _fragment_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_session_timeout_svelte"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    return Path(impl.fragment_dir) / "files" / "src" / "lib"


def _module_path() -> Path:
    return _fragment_root() / "core" / "auth" / "session-timeout.svelte.ts"


def _modal_path() -> Path:
    return _fragment_root() / "features" / "auth" / "components" / "SessionTimeoutModal.svelte"


def test_session_timeout_svelte_fragment_registered() -> None:
    from forge.config import FrontendFramework

    assert "platform_auth_session_timeout_svelte" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_session_timeout_svelte"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert impl.scope == "project"
    assert frag.target_frontends == (FrontendFramework.SVELTE,), (
        "Svelte session-timeout fragment must declare target_frontends=(SVELTE,)"
    )


def test_module_and_modal_files_shipped() -> None:
    assert _module_path().is_file(), f"session-timeout.svelte.ts missing at {_module_path()}"
    assert _modal_path().is_file(), f"SessionTimeoutModal.svelte missing at {_modal_path()}"


def test_module_uses_svelte_5_runes() -> None:
    """Reactive state must be ``$state``, computed must be ``$derived``."""
    text = _module_path().read_text(encoding="utf-8")
    assert "$state" in text, "Svelte 5 runed module must use $state for reactive state"
    assert "$derived" in text, "Svelte 5 runed module must use $derived for computed values"


def test_module_implements_drift_immune_countdown() -> None:
    """Same drift-immune contract as the Vue fragment."""
    text = _module_path().read_text(encoding="utf-8")
    assert "idleExpiresAt" in text
    assert "Date.now()" in text


def test_module_implements_cross_tab_dedup() -> None:
    text = _module_path().read_text(encoding="utf-8")
    assert "BroadcastChannel" in text
    assert "activity-claim" in text or "'activity-claim'" in text
    assert "extended" in text


def test_module_visibility_gates_extensions() -> None:
    text = _module_path().read_text(encoding="utf-8")
    assert "visibilityState" in text
    assert "'visible'" in text or '"visible"' in text


def test_module_listens_to_real_activity_events() -> None:
    text = _module_path().read_text(encoding="utf-8")
    for event in ("mousemove", "keydown", "scroll", "visibilitychange"):
        assert event in text, f"missing activity event: {event}"


def test_module_debounces_extensions() -> None:
    text = _module_path().read_text(encoding="utf-8")
    assert "30_000" in text or "30000" in text


def test_module_silently_disables_when_bootstrap_fails() -> None:
    text = _module_path().read_text(encoding="utf-8")
    assert "enabled" in text
    assert "idle_timeout_seconds === 0" in text or "idle_timeout_seconds == 0" in text


def test_module_uses_correct_endpoint_and_method_semantics() -> None:
    text = _module_path().read_text(encoding="utf-8")
    assert "/auth/session" in text
    assert "credentials: 'include'" in text
    assert "method: 'POST'" in text


def test_modal_uses_svelte_5_props_runes() -> None:
    """Modal must use ``$props()`` and ``$state``/``$derived``."""
    text = _modal_path().read_text(encoding="utf-8")
    assert "$props" in text, "Modal must declare props via Svelte 5's $props rune"
    assert "$state" in text or "$derived" in text, (
        "Modal must use Svelte 5 runes for reactive state"
    )


def test_modal_consumes_session_module_correctly() -> None:
    text = _modal_path().read_text(encoding="utf-8")
    assert "getSessionTimeout" in text, "Modal must consume the runed module's factory"
    assert "session.idleRemaining" in text
    assert "session.warnAtSeconds" in text or "warnAtSeconds" in text


def test_modal_offers_stay_signed_in_and_sign_out() -> None:
    text = _modal_path().read_text(encoding="utf-8")
    assert "Stay signed in" in text
    assert "Sign out" in text
    assert "session.extend()" in text or ".extend()" in text
    assert "/logout" in text


def test_modal_imports_from_relative_module_path() -> None:
    """Modal's import must resolve in a real SvelteKit project tree.

    The fragment ships into ``apps/frontend/src/lib/features/auth/components/``
    with the runed module at ``apps/frontend/src/lib/core/auth/``. The
    relative import must walk up to ``lib/`` then back into ``core/auth``.
    """
    text = _modal_path().read_text(encoding="utf-8")
    assert "../../../core/auth/session-timeout.svelte" in text, (
        "Modal must import the runed module via the project-relative path"
    )
