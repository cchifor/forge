"""WS-6.3: generated services must skip audit/logging for health probes.

Kubernetes liveness/readiness probes hit nested health routes. The health
router (``app/api/v1/endpoints/health.py``) exposes ``/live`` and ``/ready``;
``app/api/v1/api.py.jinja`` mounts it at ``prefix="/health"``; ``app/main.py``
mounts the v1 aggregate at ``prefix="/api/v1"``. The effective probe paths are
therefore ``/api/v1/health/live`` and ``/api/v1/health/ready``.

The shipped skip machinery matched the excluded list by *exact* equality
against bare paths like ``/health``, so the real nested probe paths were never
skipped — they were both audited and request-logged on every probe. Worse,
``main.py`` never passed any excluded paths to ``AuditMiddleware``.

This module has two layers:

  * STRUCTURAL source guards (always run; no third-party imports) mirroring
    ``test_runtime_hardening.py`` / ``test_security_config_guards.py``. These
    are the primary regression gate in CI, where the generated service's
    runtime deps (fastapi/starlette) are not installed in the forge venv.

  * BEHAVIORAL tests that import each middleware module in isolation and
    exercise the real prefix-skip decision, including boundary cases that must
    NOT be over-skipped. The middleware modules import fastapi/starlette at
    module scope, so these are skipped via ``pytest.importorskip`` when those
    runtime deps are absent (the forge tooling venv), and run for real where
    they are present (a generated-service venv).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SVC = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "templates"
    / "services"
    / "python-service-template"
    / "template"
)
_SRC = _SVC / "src"

# The real, confirmed health path prefix (health.router /live,/ready mounted at
# api.py.jinja prefix="/health", v1 aggregate mounted at main.py prefix="/api/v1").
_HEALTH_PREFIX = "/api/v1/health"

# Paths that MUST be skipped by both middlewares.
SKIP_PATHS = [
    "/api/v1/health",
    "/api/v1/health/live",
    "/api/v1/health/ready",
]

# Real business paths and boundary cases that must NOT be skipped.
NO_SKIP_PATHS = [
    "/api/v1/items",
    "/api/v1/users/42",
    "/api/v1/healthz-records",  # boundary: shares the "health" stem
    "/api/v1/healthier",  # boundary: prefix-but-not-segment
]


def _read(relpath: str) -> str:
    return (_SRC / "app" / relpath).read_text(encoding="utf-8")


def _load_module(relpath: str, name: str):
    """Import a middleware template module in isolation."""
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    spec = importlib.util.spec_from_file_location(name, _SRC / "app" / relpath)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ===========================================================================
# Structural source guards (always run — no fastapi/starlette import needed)
# ===========================================================================


def test_main_passes_excluded_paths_to_audit_middleware() -> None:
    content = _read("main.py")
    assert "AuditMiddleware, excluded_paths=" in content, (
        "main.py must forward the excluded paths to AuditMiddleware"
    )


def test_audit_config_default_covers_real_health_prefix() -> None:
    content = (_SRC / "app" / "core" / "config" / "domain.py").read_text(
        encoding="utf-8"
    )
    assert '"/api/v1/health"' in content, (
        "AuditConfig.excluded_paths must include the real health prefix"
    )


def test_shipped_yaml_config_covers_real_health_prefix() -> None:
    """The runtime default.yaml ALWAYS loads and REPLACES the model's
    excluded_paths default (the config loader does list-replace, not merge), so
    the shipped YAML — not just the Python default — must list the real health
    prefix or generated services audit + log every probe. This is the
    load-bearing guard the Python-default tests above do NOT cover."""
    yaml_src = (_SVC / "config" / "default.yaml.jinja").read_text(encoding="utf-8")
    audit_block = yaml_src.split("audit:", 1)[1]
    assert '"/api/v1/health"' in audit_block, (
        "config/default.yaml.jinja audit.excluded_paths must include "
        '"/api/v1/health" — it overrides the Python default at load time'
    )


def test_audit_empty_config_is_honored_not_overridden() -> None:
    """An explicit empty excluded_paths must mean 'audit everything', not
    silently fall back to the hardcoded default. The constructor must branch on
    ``is None``, not truthiness."""
    content = _read("middleware/audit.py")
    assert "excluded_paths or {" not in content and "excluded_paths or{" not in content, (
        "audit must not use `excluded_paths or {...}` (an explicit empty set "
        "would be swallowed); use `excluded_paths if excluded_paths is not None`"
    )
    assert "if excluded_paths is not None" in content


def test_audit_middleware_default_covers_real_health_prefix() -> None:
    assert '"/api/v1/health"' in _read("middleware/audit.py")


def test_audit_middleware_uses_prefix_match_not_bare_in() -> None:
    content = _read("middleware/audit.py")
    assert "startswith" in content, "audit dispatch must be prefix-aware"
    assert "request.url.path in self.excluded_paths" not in content, (
        "audit dispatch must not use bare exact membership"
    )


def test_logging_middleware_uses_prefix_match_not_bare_in() -> None:
    content = _read("middleware/logging.py")
    assert "startswith" in content, "logging dispatch must be prefix-aware"
    assert "request.url.path in self.skip_paths" not in content, (
        "logging dispatch must not use bare exact membership"
    )


# ===========================================================================
# Behavioral tests (require the generated service's runtime deps)
# ===========================================================================

# The middleware modules import fastapi/starlette at module scope. Those are
# part of the *generated* service's deps, not the forge tooling venv. Use a
# per-test skipif (NOT a module-level importorskip, which would skip the
# structural guards above too — those must remain the regression gate in CI).
import importlib.util as _ilu  # noqa: E402

_HAS_RUNTIME_DEPS = bool(
    _ilu.find_spec("fastapi") and _ilu.find_spec("starlette")
)
_needs_runtime = pytest.mark.skipif(
    not _HAS_RUNTIME_DEPS,
    reason="fastapi/starlette required to import the middleware modules",
)


def _audit_mw():
    audit = _load_module("middleware/audit.py", "audit_tmpl")
    # Mirror the real main.py wiring: pass the excluded paths explicitly.
    return audit.AuditMiddleware(None, excluded_paths={_HEALTH_PREFIX, "/metrics"})


@_needs_runtime
@pytest.mark.parametrize("path", SKIP_PATHS)
def test_audit_skips_health_paths(path: str) -> None:
    assert _audit_mw()._is_excluded(path) is True, path


@_needs_runtime
@pytest.mark.parametrize("path", NO_SKIP_PATHS)
def test_audit_does_not_skip_business_paths(path: str) -> None:
    assert _audit_mw()._is_excluded(path) is False, path


@_needs_runtime
def test_audit_default_excluded_paths_cover_real_health_prefix() -> None:
    audit = _load_module("middleware/audit.py", "audit_tmpl")
    mw = audit.AuditMiddleware(None)  # fall back to shipped default set
    assert mw._is_excluded("/api/v1/health/live") is True


@_needs_runtime
def test_audit_explicit_empty_set_audits_everything() -> None:
    """An explicit empty exclusion set must be honored (audit everything), not
    replaced by the hardcoded default."""
    audit = _load_module("middleware/audit.py", "audit_tmpl")
    mw = audit.AuditMiddleware(None, excluded_paths=set())
    assert mw._is_excluded("/api/v1/health/live") is False
    assert mw.excluded_paths == set()


def _logging_mw():
    logging_mod = _load_module("middleware/logging.py", "logging_tmpl")
    return logging_mod.RequestLoggingMiddleware(
        None, skip_paths=[_HEALTH_PREFIX, "/metrics"]
    )


@_needs_runtime
@pytest.mark.parametrize("path", SKIP_PATHS)
def test_logging_skips_health_paths(path: str) -> None:
    assert _logging_mw()._should_skip(path) is True, path


@_needs_runtime
@pytest.mark.parametrize("path", NO_SKIP_PATHS)
def test_logging_does_not_skip_business_paths(path: str) -> None:
    assert _logging_mw()._should_skip(path) is False, path
