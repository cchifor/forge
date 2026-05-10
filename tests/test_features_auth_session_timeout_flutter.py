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


# -- Native auth refresh path ---------------------------------------------------
#
# The session-timeout service ships a dedicated ``forNative`` factory
# that uses an injected ``RefreshAccessToken`` callback (wired to the
# host app's ``AuthRepository.refreshAccessToken``) instead of POSTing
# to ``/auth/session`` (which is cookie-only). These invariants pin the
# native code path so a future regression that drops the factory or its
# refresh-token wiring surfaces here at forge generate time.


def test_service_exposes_session_timeout_mode_enum() -> None:
    """``SessionTimeoutMode { web, native }`` distinguishes the two
    code paths inside the service. Pinned so the dual model stays
    explicit rather than collapsing back to a kIsWeb branch."""
    text = _service_path().read_text(encoding="utf-8")
    assert "enum SessionTimeoutMode" in text, (
        "Service must declare a SessionTimeoutMode enum to distinguish "
        "the cookie-based BFF path (web) from the refresh-token path "
        "(native)"
    )
    assert "SessionTimeoutMode.web" in text
    assert "SessionTimeoutMode.native" in text


def test_service_exposes_refresh_access_token_typedef() -> None:
    """``RefreshAccessToken`` typedef lets the consumer wire
    ``AuthRepository.refreshAccessToken`` (or any other rotation
    function) without the service taking a hard dep on the host app's
    auth layer."""
    text = _service_path().read_text(encoding="utf-8")
    assert "typedef RefreshAccessToken" in text, (
        "Service must declare a RefreshAccessToken typedef so the "
        "native code path takes the rotation function as a callback"
    )
    # Returns the new access token's expiry so the service can reset
    # its drift-immune countdown anchor.
    assert "Future<DateTime?> Function()" in text, (
        "RefreshAccessToken must be Future<DateTime?> Function() — "
        "returns the new access token's expiry timestamp"
    )


def test_service_ships_native_factory() -> None:
    """``SessionTimeoutService.forNative(...)`` is the dedicated
    constructor for non-cookie clients. It MUST take a
    ``refreshAccessToken`` callback (no default — every native consumer
    must wire its own auth repository)."""
    text = _service_path().read_text(encoding="utf-8")
    assert "SessionTimeoutService.forNative" in text, (
        "Service must ship a forNative factory constructor"
    )
    assert "required RefreshAccessToken refreshAccessToken" in text, (
        "forNative factory must require a refreshAccessToken callback"
    )
    # Defaults mirror the Gatekeeper's per-tenant defaults so cross-
    # platform behavior aligns.
    assert "idleTimeoutSeconds" in text
    assert "absoluteTimeoutSeconds" in text
    assert "warnAtSeconds" in text
    # Native consumers wire onForcedLogout to AuthRepository.logout()
    # plus a navigation to the login route.
    assert "onForcedLogout" in text, (
        "forNative factory must accept an onForcedLogout callback so "
        "the host app can clear tokens + navigate on idle / absolute "
        "timeout or refresh-token rejection"
    )


def test_service_native_path_does_not_post_to_auth_session() -> None:
    """Native bypasses the Gatekeeper /auth/session endpoint (cookie-
    only). The service's native code path MUST call the refresh
    callback rather than POSTing."""
    text = _service_path().read_text(encoding="utf-8")
    assert "_extendNative" in text, (
        "Service must split the extend path into a native variant "
        "that delegates to the refresh-token callback"
    )
    # The native bootstrap is local-only (no server roundtrip) — no
    # baseline cookie GET to fall back to.
    assert "_bootstrapNative" in text, (
        "Service must split the bootstrap path so native computes "
        "initial countdown from the configured idle/absolute timeouts "
        "without a server call"
    )


def test_service_forces_logout_on_idle_or_absolute_timeout() -> None:
    """When either countdown elapses on native, the service must
    invoke the onForcedLogout callback. Without this, the user would
    sit on a stale UI past the compliance idle window."""
    text = _service_path().read_text(encoding="utf-8")
    assert "_onForcedLogout" in text
    # Tick timer must check countdown values and fire the callback.
    assert "absoluteRemainingSeconds <= 0" in text or "idleRemainingSeconds <= 0" in text, (
        "Tick timer must detect idle / absolute timeout elapsed on "
        "native and invoke the forced-logout callback"
    )


def test_modal_documents_native_signout_requirement() -> None:
    """The modal's onSignOut callback is consumer-supplied. On native,
    the consumer MUST pass it (typically AuthRepository.logout + a
    navigation). The doc-comment makes this explicit."""
    text = _modal_path().read_text(encoding="utf-8")
    assert "Native consumers MUST pass it" in text, (
        "Modal doc must call out that native consumers must pass "
        "onSignOut explicitly"
    )


# -- Base flutter-frontend-template wiring -------------------------------------
#
# The session-timeout fragment is half the story; the native
# refresh-token rotation is wired through the base flutter-frontend-
# template's auth layer. These invariants pin the supporting public
# surface so a refactor can't silently strip the integration points
# the fragment depends on.

_FLUTTER_TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "forge"
    / "templates"
    / "apps"
    / "flutter-frontend-template"
    / "{{project_slug}}"
    / "lib"
    / "src"
)


def test_keycloak_auth_service_exposes_refresh_access_token() -> None:
    """``KeycloakAuthService.refreshAccessToken`` is the native
    rotation primitive the session-timeout service's forNative factory
    delegates to. Pinned as a public method so a refactor can't
    accidentally re-privatize it (the flow already existed in
    ``init()``; this method is the extracted public surface)."""
    text = (
        _FLUTTER_TEMPLATE_ROOT / "features" / "auth" / "data" / "keycloak_auth_service.dart"
    ).read_text(encoding="utf-8")
    assert "Future<DateTime?> refreshAccessToken()" in text, (
        "KeycloakAuthService must expose a public Future<DateTime?> "
        "refreshAccessToken() method that returns the new access "
        "token's expiry timestamp"
    )
    # The rotation must go through flutter_appauth's token endpoint
    # with the stored refresh token (the existing init() pattern,
    # extracted into a shared helper).
    assert "_rotateFromRefreshToken" in text, (
        "Rotation should live in a shared private helper so init() "
        "and refreshAccessToken() use one code path"
    )


def test_auth_repository_delegates_refresh_to_keycloak() -> None:
    """``AuthRepository.refreshAccessToken`` returns null on dev / web
    and delegates to ``KeycloakAuthService.refreshAccessToken`` on
    native. The session-timeout service's forNative factory wires
    this method as its rotation callback."""
    text = (
        _FLUTTER_TEMPLATE_ROOT / "features" / "auth" / "data" / "auth_repository.dart"
    ).read_text(encoding="utf-8")
    assert "Future<DateTime?> refreshAccessToken()" in text, (
        "AuthRepository must expose refreshAccessToken() so the "
        "session-timeout service can call it as a callback"
    )
    assert "if (_authDisabled || _useGatekeeper) return null" in text, (
        "Web / dev paths must short-circuit to null (the cookie-based "
        "BFF flow doesn't manage refresh tokens client-side)"
    )


def test_auth_interceptor_retries_once_on_401() -> None:
    """The Dio auth interceptor catches 401, attempts a single refresh,
    then retries the request. Mirrors the standard mobile-OIDC pattern.
    Pinned so the retry path can't regress to the original
    inject-only-on-outbound shape."""
    text = (
        _FLUTTER_TEMPLATE_ROOT / "api" / "client" / "auth_interceptor.dart"
    ).read_text(encoding="utf-8")
    # The retry guard prevents infinite recursion on a second 401.
    assert "_retriedFlag" in text or "retried" in text, (
        "Interceptor must mark already-retried requests so a second "
        "401 doesn't trigger another refresh attempt"
    )
    # The retry must call refresh THEN replay the request.
    assert "refreshAccessToken" in text, (
        "Interceptor must call refreshAccessToken() on 401"
    )
    assert "dio.fetch" in text, (
        "Interceptor must replay the original request via dio.fetch "
        "after rotating the access token"
    )
    # Web bypass — the cookie-based flow uses redirect handling.
    assert "kIsWeb" in text, (
        "Interceptor must skip the 401 retry on web (cookie-based "
        "auth uses a different recovery path)"
    )
