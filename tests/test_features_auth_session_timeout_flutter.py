"""Invariants for the Flutter session-timeout fragment (Phase 8).

Mirrors ``test_features_auth_session_timeout_vue.py`` and
``test_features_auth_session_timeout_svelte.py`` — same RFC constraints
ported to Flutter idioms (``ChangeNotifier``, ``WidgetsBindingObserver``,
``Timer.periodic``, ``DateTime.now()``).

Cross-tab leader election (BroadcastChannel) is web-only and explicitly
deferred to a follow-up sub-phase; this test does NOT assert it on
Flutter, since on native there is no equivalent (single app instance
per device). The ``dart:js_interop`` binding for BroadcastChannel on
Flutter web ships separately.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


def _fragment_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_session_timeout_flutter"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    return Path(impl.fragment_dir) / "files" / "lib" / "src" / "features" / "auth"


def _service_path() -> Path:
    return _fragment_root() / "data" / "session_timeout_service.dart"


def _modal_path() -> Path:
    return _fragment_root() / "presentation" / "session_timeout_modal.dart"


def test_session_timeout_flutter_fragment_registered() -> None:
    from forge.config import FrontendFramework

    assert "platform_auth_session_timeout_flutter" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_session_timeout_flutter"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    assert impl.scope == "project"
    assert frag.target_frontends == (FrontendFramework.FLUTTER,), (
        "Flutter session-timeout fragment must declare target_frontends=(FLUTTER,)"
    )


def test_service_and_modal_files_shipped() -> None:
    assert _service_path().is_file(), (
        f"session_timeout_service.dart missing at {_service_path()}"
    )
    assert _modal_path().is_file(), (
        f"session_timeout_modal.dart missing at {_modal_path()}"
    )


def test_service_implements_drift_immune_countdown() -> None:
    """Service must store ``idleExpiresAt`` and recompute via DateTime.now()."""
    text = _service_path().read_text(encoding="utf-8")
    assert "_idleExpiresAt" in text or "idleExpiresAt" in text, (
        "Service must store an absolute target DateTime"
    )
    assert "DateTime.now()" in text, (
        "Service must compute remaining via DateTime.now() at read time"
    )


def test_service_uses_widgets_binding_observer_for_visibility() -> None:
    """Visibility on Flutter is `AppLifecycleState`, not `document.visibilityState`."""
    text = _service_path().read_text(encoding="utf-8")
    assert "WidgetsBindingObserver" in text, (
        "Service must mix in WidgetsBindingObserver for lifecycle awareness"
    )
    assert "AppLifecycleState" in text, (
        "Service must check AppLifecycleState (resumed = visible)"
    )
    assert "didChangeAppLifecycleState" in text, (
        "Service must override didChangeAppLifecycleState"
    )


def test_service_listens_to_activity_hints() -> None:
    """Activity hints must mirror Vue/Svelte event names cross-platform."""
    text = _service_path().read_text(encoding="utf-8")
    for event in ("mousemove", "keydown", "scroll", "visibilitychange"):
        assert event in text, (
            f"Service must accept '{event}' activity hint to keep "
            f"telemetry semantics aligned across platforms"
        )


def test_service_debounces_extensions() -> None:
    """30-second debounce default."""
    text = _service_path().read_text(encoding="utf-8")
    # Dart syntax — `Duration(seconds: 30)` as the default.
    assert "Duration(seconds: 30)" in text or "_defaultDebounce" in text, (
        "Service must default to 30-second debounce window"
    )


def test_service_silently_disables_when_bootstrap_fails() -> None:
    text = _service_path().read_text(encoding="utf-8")
    assert "_enabled" in text, "Service must expose an enabled flag"
    assert "serverSideDisabled" in text, (
        "Service must detect server-disabled timeouts (idle=0 && absolute=0)"
    )


def test_service_uses_correct_endpoint_and_methods() -> None:
    text = _service_path().read_text(encoding="utf-8")
    assert "/auth/session" in text
    # Dart's http package uses .get / .post for HTTP methods.
    assert ".get(endpoint" in text or "_http.get(" in text
    assert ".post(endpoint" in text or "_http.post(" in text


def test_service_extends_change_notifier() -> None:
    """ChangeNotifier is the framework-agnostic observable shape.

    Works with Provider, Riverpod, or manual ListenableBuilder.
    """
    text = _service_path().read_text(encoding="utf-8")
    assert "extends ChangeNotifier" in text, (
        "Service must extend ChangeNotifier to be observable from any "
        "Flutter state-management layer"
    )
    assert "notifyListeners" in text, (
        "Service must call notifyListeners() to propagate state changes"
    )


def test_modal_consumes_service_via_listenable_builder() -> None:
    """Modal observes the service via ``ListenableBuilder`` so it
    rebuilds on state changes (countdown ticks + enabled flag flips)
    without forcing a specific state-management library."""
    text = _modal_path().read_text(encoding="utf-8")
    assert "ListenableBuilder" in text, (
        "Modal must use ListenableBuilder to observe the service"
    )
    assert "SessionTimeoutService" in text, (
        "Modal must accept a SessionTimeoutService instance"
    )


def test_modal_opens_at_warn_threshold() -> None:
    text = _modal_path().read_text(encoding="utf-8")
    assert "warnAtSeconds" in text, "Modal must consume warnAtSeconds threshold"
    assert "idleRemainingSeconds" in text or "remaining" in text


def test_modal_offers_stay_signed_in_and_sign_out() -> None:
    text = _modal_path().read_text(encoding="utf-8")
    assert "Stay signed in" in text
    assert "Sign out" in text
    assert ".extend()" in text or "service.extend" in text, (
        "Modal's 'Stay signed in' must call service.extend()"
    )
