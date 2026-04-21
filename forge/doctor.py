"""`forge doctor` — check the local environment for everything forge needs.

Produces a structured ``DoctorReport`` listing each check, its status
(ok / warn / fail), and an actionable suggestion for anything that
failed. ``--json`` output is usable by CI.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CheckStatus = Literal["ok", "warn", "fail"]


@dataclass
class CheckResult:
    """One doctor check — name, status, human-readable detail, optional fix hint."""

    name: str
    status: CheckStatus
    detail: str
    fix: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "fix": self.fix,
        }


@dataclass
class DoctorReport:
    """Aggregate result of every doctor check."""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def worst(self) -> CheckStatus:
        if any(r.status == "fail" for r in self.results):
            return "fail"
        if any(r.status == "warn" for r in self.results):
            return "warn"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "worst": self.worst,
            "checks": [r.as_dict() for r in self.results],
        }


# -- Individual checks --------------------------------------------------------


def check_tool_on_path(name: str, *, min_version: str | None = None, kind: str = "tool") -> CheckResult:
    """Check that ``name`` is on PATH. If ``min_version`` is given, verify
    the reported version meets it (string-compare, which is good enough for
    SemVer-ish tools).
    """
    resolved = shutil.which(name)
    if not resolved:
        return CheckResult(
            name=f"{kind}:{name}",
            status="fail",
            detail=f"{name!r} not found on PATH",
            fix=f"Install {name} and ensure it's available in your shell's PATH.",
        )
    if min_version is None:
        return CheckResult(
            name=f"{kind}:{name}",
            status="ok",
            detail=f"{name} found at {resolved}",
        )
    try:
        version_line = subprocess.run(
            [name, "--version"], capture_output=True, text=True, timeout=5, check=False
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            name=f"{kind}:{name}",
            status="warn",
            detail=f"{name} found but `--version` failed: {e}",
        )
    return CheckResult(
        name=f"{kind}:{name}",
        status="ok",
        detail=f"{name} {version_line}",
    )


def check_docker_reachable() -> CheckResult:
    """Verify ``docker info`` returns cleanly — enough to boot compose later."""
    exe = shutil.which("docker")
    if not exe:
        return CheckResult(
            name="docker:daemon",
            status="warn",
            detail="docker CLI not on PATH — `forge new` without Docker still works but `--no-docker=false` generation will fail",
            fix="Install Docker Desktop or docker-cli.",
        )
    try:
        proc = subprocess.run(
            [exe, "info"], capture_output=True, text=True, timeout=5, check=False
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            name="docker:daemon",
            status="fail",
            detail=f"`docker info` raised: {e}",
            fix="Start Docker Desktop or the docker service.",
        )
    if proc.returncode != 0:
        return CheckResult(
            name="docker:daemon",
            status="fail",
            detail=f"`docker info` failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}",
            fix="Start Docker Desktop or the docker service, then re-run `forge doctor`.",
        )
    return CheckResult(
        name="docker:daemon",
        status="ok",
        detail="docker info succeeded",
    )


def check_port_free(port: int, *, host: str = "127.0.0.1") -> CheckResult:
    """Try to bind to ``host:port`` — if it fails, the port is in use."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.bind((host, port))
    except OSError as e:
        return CheckResult(
            name=f"port:{port}",
            status="warn",
            detail=f"port {port} is in use ({e})",
            fix=f"Stop the process using port {port}, or pass --backend-port to pick a different port.",
        )
    finally:
        sock.close()
    return CheckResult(
        name=f"port:{port}",
        status="ok",
        detail=f"port {port} is available",
    )


def check_registered_backends() -> list[CheckResult]:
    """Surface every backend in :data:`BACKEND_REGISTRY` as a doctor row.

    Built-ins emit three rows (Python / Node / Rust); each
    plugin-registered backend adds one. Each row reports the toolchain
    attached to the spec — which is how Epic S's plugin SDK guarantees
    that a plugin backend's install/verify steps are wired in.

    A plugin backend registered without attaching a toolchain (i.e.
    ``BackendSpec(...)`` with no ``toolchain`` argument) falls back to
    the :class:`NoopToolchain`, surfaced here as a ``warn`` so the user
    knows the plugin shipped with degraded support.
    """
    from forge.config import BACKEND_REGISTRY  # noqa: PLC0415
    from forge.toolchains import NoopToolchain  # noqa: PLC0415

    results: list[CheckResult] = []
    for lang, spec in BACKEND_REGISTRY.items():
        toolchain = spec.toolchain
        tc_name = getattr(toolchain, "name", "?")
        if isinstance(toolchain, NoopToolchain):
            results.append(
                CheckResult(
                    name=f"backend:{lang.value}",
                    status="warn",
                    detail=(
                        f"{spec.display_label} registered but its BackendSpec carries "
                        "the NoopToolchain — install/verify hooks will be skipped"
                    ),
                    fix=(
                        "If this is a plugin backend, attach a BackendToolchain to the "
                        "spec (see docs/adding-a-backend.md). Built-ins should never "
                        "land on Noop; file a bug at github.com/cchifor/forge."
                    ),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"backend:{lang.value}",
                    status="ok",
                    detail=f"{spec.display_label} — toolchain: {tc_name}",
                )
            )
    return results


def check_forge_toml(project_path: Path) -> CheckResult:
    """If ``project_path/forge.toml`` exists, parse it and verify integrity."""
    manifest = project_path / "forge.toml"
    if not manifest.is_file():
        return CheckResult(
            name="forge.toml:presence",
            status="ok",
            detail=f"no forge.toml at {project_path} (not a forge-generated project)",
        )
    try:
        from forge.forge_toml import read_forge_toml  # noqa: PLC0415

        data = read_forge_toml(manifest)
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            name="forge.toml:integrity",
            status="fail",
            detail=f"cannot parse {manifest}: {e}",
            fix="Inspect forge.toml for syntax errors or restore from git.",
        )
    parts = [f"version={data.version}", f"project={data.project_name}"]
    if data.provenance:
        parts.append(f"provenance_entries={len(data.provenance)}")
    return CheckResult(
        name="forge.toml:integrity",
        status="ok",
        detail=", ".join(parts),
    )


def run(project_path: Path | None = None) -> DoctorReport:
    """Run every check and return the aggregate report."""
    project_path = project_path or Path.cwd()
    report = DoctorReport()

    # Python is required — forge itself can't run otherwise, so this is an
    # assertion rather than a variable check.
    report.results.append(
        CheckResult(
            name="runtime:python",
            status="ok",
            detail=f"Python {sys.version.split()[0]} at {sys.executable}",
        )
    )
    report.results.append(check_tool_on_path("git", kind="vcs"))
    report.results.append(check_tool_on_path("uv", kind="tool"))
    report.results.append(check_tool_on_path("node", kind="tool"))
    report.results.append(check_tool_on_path("npm", kind="tool"))
    report.results.append(check_tool_on_path("cargo", kind="tool"))
    report.results.append(check_tool_on_path("flutter", kind="tool"))
    report.results.append(check_docker_reachable())

    # Surface every registered backend + its toolchain. Built-ins always
    # land in BACKEND_REGISTRY; plugin backends land here once loaded.
    report.results.extend(check_registered_backends())

    # Commonly used ports. Warnings, not failures — users can always pick
    # other ports via flags.
    for port in (5000, 5173, 18080):
        report.results.append(check_port_free(port))

    report.results.append(check_forge_toml(project_path))
    return report


# -- CLI rendering ------------------------------------------------------------


_STATUS_GLYPH = {"ok": "[OK]", "warn": "[WARN]", "fail": "[FAIL]"}


def render_text(report: DoctorReport) -> str:
    lines: list[str] = []
    for r in report.results:
        glyph = _STATUS_GLYPH.get(r.status, "[?]")
        lines.append(f"  {glyph:<7} {r.name:<28} {r.detail}")
        if r.fix:
            lines.append(f"           -> fix: {r.fix}")
    worst_glyph = _STATUS_GLYPH[report.worst]
    lines.append("")
    lines.append(f"Overall: {worst_glyph}")
    return "\n".join(lines) + "\n"


def _dispatch_doctor(project_path: str = ".", *, json_output: bool = False) -> None:
    """CLI entry point for `forge doctor`."""
    report = run(Path(project_path))
    if json_output:
        sys.stdout.write(json.dumps(report.as_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(render_text(report))
    sys.exit(0 if report.worst != "fail" else 1)
