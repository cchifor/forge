"""Guards for generated Python service runtime hardening (WS-6)."""

from __future__ import annotations

from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_SVC = _BASE / "forge/templates/services/python-service-template/template"


def test_production_overrides_silenced_log_level() -> None:
    """default.yaml ships log_level "critical" (quiet local/test); production
    must override it so the deployed service emits uvicorn access/info logs."""
    prod = (_SVC / "config/production.yaml").read_text(encoding="utf-8")
    assert "log_level:" in prod, "production.yaml must set server.log_level"
    assert 'log_level: "critical"' not in prod, (
        "production.yaml must not run uvicorn at critical (silences prod logs)"
    )


def test_readiness_probe_returns_503_on_dependency_error() -> None:
    """A raising dependency check (e.g. DB unreachable) must yield 503 (not
    ready), not an unguarded 500."""
    src = (_SVC / "src/app/api/v1/endpoints/health.py").read_text(encoding="utf-8")
    readiness = src.split("readiness_probe")[1]
    assert "try:" in readiness and "except" in readiness, (
        "readiness_probe must guard the dependency check"
    )
    assert "HTTP_503_SERVICE_UNAVAILABLE" in readiness
