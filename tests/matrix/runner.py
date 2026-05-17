"""Config-matrix validation runner (Epic S / sprint 1 deliverable).

Drives each scenario in ``tests/matrix/scenarios.yaml`` through one or
more lanes:

- **Lane A — generate**: invokes :func:`forge.generator.generate` into a
  fresh tempdir and asserts the expected-file manifest is present.
  Runs on every PR, ~1 min/scenario.
- **Lane B — toolchain verify**: sprint 2 deliverable (placeholder hook
  exists below). Invokes each backend's :class:`BackendToolchain.verify`
  plus the frontend build.
- **Lane C — compose-up smoke**: sprint 2 deliverable. Runs
  ``docker compose up``, waits on healthchecks, runs the RFC-006 HTTP
  contract, tears down.
- **Lane D — bidirectional round-trip** (Phase 5/6). For each opted-in
  scenario: generate → assert FR1 (zero block/files harvest candidates
  on the fresh project) → stage a synthetic literal-block edit →
  harvest → apply the bundle to the live forge tree (snapshotted +
  reverted in ``finally``) → regenerate → assert FR2 (project_a ==
  project_b modulo documented noise). ~30-90s per scenario, nightly
  only. See ``docs/round-trip.md`` for the contract.
- **Lane E — forge --update + --harvest e2e** (WS4). For each scenario,
  shells out to ``python -m forge --update --mode {merge,skip,overwrite}``
  against an edited project (per-mode contract validated) plus a single
  ``forge --harvest --harvest-out=-`` JSON-on-stdout probe. Exercises
  the argparse + builder + dispatcher path real users hit, complementing
  lane D's direct-Python-API round-trip. Nightly only; see
  ``tests/matrix/update_contract.py`` for the per-mode assertion details.

CLI usage (from the repo root)::

    uv run python tests/matrix/runner.py --all                  # all scenarios, lane A
    uv run python tests/matrix/runner.py --scenario py_vue_full
    uv run python tests/matrix/runner.py --list                 # list scenarios + lanes
    uv run python tests/matrix/runner.py --all --lane generate  # explicit lane
    uv run python tests/matrix/runner.py --scenario py_only_headless --lane roundtrip

Lane D (``roundtrip``) — Phase 5/6. Enforces FR1 (fresh-generate emits
zero block/files harvest candidates) AND FR2 (the full forward→reverse
→forward cycle reaches a project tree byte-equal to the user's edit,
modulo documented noise). Phase 6 wired the block apply-back surface
and the live-forge snapshot+restore guard so the second generate
re-emits the harvested edit. Runs nightly only via
``.github/workflows/matrix-nightly.yml``.

Exit codes::

    0 — all selected scenarios passed the requested lane
    2 — at least one scenario failed
    3 — runner misconfiguration (bad scenarios.yaml, missing forge)

Imports :mod:`forge.generator` directly rather than shelling out to the
``forge`` CLI. That's deliberate for lane A — it's faster, gives better
tracebacks, and bypasses the argparse / headless-detection code paths
the CLI suite covers. Lane C will shell out.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import yaml

Lane = Literal["generate", "verify", "smoke", "roundtrip", "update"]
ALL_LANES: tuple[Lane, ...] = ("generate", "verify", "smoke", "roundtrip", "update")

SCENARIOS_YAML = Path(__file__).parent / "scenarios.yaml"
WELD_STUBS_DIR = Path(__file__).parent / "fixtures" / "sdks"


_INSTALL_TIMEOUT_SECONDS = 300
_BUILD_TIMEOUT_SECONDS = 180


def _verify_frontend(fe_cfg, fe_dir: Path) -> str | None:
    """Run a build/analyze check against the generated frontend.

    Lane B's frontend complement to ``BackendToolchain.verify`` — runs
    ``<pm> install`` + ``<pm> run build`` in the generated
    ``apps/frontend/`` so vue-tsc / svelte-check / vite build regressions
    surface on PR rather than waiting for nightly compose-up (lane C).

    Returns ``None`` on success, an error label on failure. Uses the
    package manager from ``fe_cfg.package_manager`` when present;
    falls back to ``npm``.

    Budget (worst-case wall-clock per scenario): install 5 min +
    build 3 min = 8 min. Lane B aims for ~5 min average across the
    matrix; the upper bound covers cold CI caches without letting a
    runaway process stall the whole runner.

    Skips silently (returns ``None``) when:

    * The frontend framework is Flutter — ``subosito/flutter-action`` is
      heavy and lane B targets <5 min/scenario; Flutter is covered by
      ``tests/e2e/test_full_generation.py::test_flutter_*``.
    * No frontend framework is set on the FrontendConfig (defensive —
      callers gate on this too).
    * The configured package manager (and the ``npm`` fallback) is not
      on PATH — developer machines without a Node toolchain shouldn't
      see spurious failures; same pattern as ``run_lane_smoke``'s
      docker-availability check.
    """
    from forge.config import FrontendFramework  # noqa: PLC0415

    framework = getattr(fe_cfg, "framework", None)
    if framework is None or framework == FrontendFramework.NONE:
        return None
    if getattr(framework, "value", None) == "flutter":
        # Flutter handled by e2e suite (subosito/flutter-action heavy install).
        return None
    pm = getattr(fe_cfg, "package_manager", "npm") or "npm"
    pm_exe = shutil.which(pm) or shutil.which("npm")
    if pm_exe is None:
        return None  # No JS runtime on this runner — skip silently.
    return _run_frontend_step(
        pm, pm_exe, fe_dir, ["install", "--no-fund", "--no-audit"], _INSTALL_TIMEOUT_SECONDS
    ) or _run_frontend_step(pm, pm_exe, fe_dir, ["run", "build"], _BUILD_TIMEOUT_SECONDS)


def _run_frontend_step(
    pm: str, pm_exe: str, fe_dir: Path, args: list[str], timeout: int
) -> str | None:
    """Run a single package-manager step; return failure label or None.

    Translates :class:`subprocess.TimeoutExpired` and
    :class:`FileNotFoundError` into failure labels rather than letting
    them propagate out of the runner — a runaway ``npm install`` must
    not take out the whole matrix run by crashing ``main()``. Mirrors
    the pattern in ``forge.toolchains._runner._run_check``.
    """
    import subprocess  # noqa: PLC0415

    label = f"{pm} {' '.join(args)}"
    try:
        result = subprocess.run(
            [pm_exe, *args],
            cwd=fe_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"{label} timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"{label} could not exec {pm_exe}: {e}"
    if result.returncode == 0:
        return None
    stream = result.stderr.strip() or result.stdout.strip()
    tail = "\n".join(stream.splitlines()[-3:]) if stream else "<no output>"
    return f"{label} failed (exit {result.returncode}): {tail}"


def _inject_weld_stubs(project_root: Path) -> None:
    """Drop matrix-CI weld-* SDK stub packages into ``<project>/sdks/``.

    Generated Python services declare ``[tool.uv.sources]`` entries
    pointing at ``../../sdks/weld-<name>/`` — the platform monorepo's
    in-tree SDK paths. Matrix CI has no platform sibling tree, so the
    real weld-* sources are unavailable and ``uv sync`` fails. These
    minimal namespace-package stubs (defined under
    ``tests/matrix/fixtures/sdks/``) let the verify lane run end-to-end
    (uv sync → ruff → ty → pytest) without the real weld monorepo.

    The stubs expose the same import surface as ``weld-*`` and contain
    just enough behavior for the template's tests to pass against
    ``sqlite+aiosqlite``: TenantMixin/UserOwnedMixin/TimestampMixin
    register SQLAlchemy columns, AsyncBaseRepository implements
    ``_get_base_query`` / ``_to_schema`` / CRUD verbs, the auth
    fragment's ``Error`` envelope round-trips, ``Account`` normalizes
    UUID strings, and so on.

    Idempotent — ``weld-*`` sub-dirs are skipped if already present
    (the auth fragment ships its own ``sdks/platform-auth/``).
    """
    if not WELD_STUBS_DIR.is_dir():
        return
    sdks_dir = project_root / "sdks"
    sdks_dir.mkdir(parents=True, exist_ok=True)
    for stub in WELD_STUBS_DIR.iterdir():
        if not stub.is_dir() or not stub.name.startswith("weld-"):
            continue
        target = sdks_dir / stub.name
        if target.exists():
            continue
        shutil.copytree(str(stub), str(target))


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    lanes: tuple[Lane, ...]
    port_base: int
    expected_files: tuple[str, ...]
    config: dict[str, Any]


@dataclass
class LaneResult:
    scenario: str
    lane: Lane
    status: Literal["ok", "fail", "skip"]
    duration_ms: int
    details: str = ""
    missing_files: list[str] = field(default_factory=list)


def load_scenarios(path: Path = SCENARIOS_YAML) -> list[Scenario]:
    """Parse ``scenarios.yaml`` into :class:`Scenario` records.

    Raises ``ValueError`` on schema violations — the runner treats that
    as exit-code 3 (misconfiguration) rather than per-scenario failure.
    """
    if not path.exists():
        raise ValueError(f"scenarios.yaml not found at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("scenarios.yaml must be a mapping at the top level")

    version = data.get("schema_version")
    if version != 1:
        raise ValueError(f"scenarios.yaml schema_version must be 1, got {version!r}")

    raw_scenarios = data.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("scenarios.yaml must define a non-empty 'scenarios' list")

    scenarios: list[Scenario] = []
    seen_names: set[str] = set()
    seen_ports: dict[int, str] = {}
    for i, raw in enumerate(raw_scenarios):
        if not isinstance(raw, dict):
            raise ValueError(f"scenario #{i} is not a mapping")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"scenario #{i} missing non-empty 'name'")
        if name in seen_names:
            raise ValueError(f"scenario name {name!r} duplicated")
        seen_names.add(name)
        port_base = raw.get("port_base")
        if not isinstance(port_base, int):
            raise ValueError(f"scenario {name!r} needs integer 'port_base'")
        if port_base in seen_ports:
            raise ValueError(
                f"scenario {name!r} reuses port_base {port_base} already claimed "
                f"by {seen_ports[port_base]!r}"
            )
        seen_ports[port_base] = name

        lanes_raw = raw.get("lanes", list(ALL_LANES))
        if not isinstance(lanes_raw, list):
            raise ValueError(f"scenario {name!r} 'lanes' must be a list")
        for lane in lanes_raw:
            if lane not in ALL_LANES:
                raise ValueError(
                    f"scenario {name!r} has unknown lane {lane!r}; expected one of {ALL_LANES}"
                )

        expected = raw.get("expected_files", [])
        if not isinstance(expected, list) or not all(isinstance(f, str) for f in expected):
            raise ValueError(f"scenario {name!r} 'expected_files' must be list[str]")

        cfg = raw.get("config")
        if not isinstance(cfg, dict):
            raise ValueError(f"scenario {name!r} 'config' must be a mapping")

        scenarios.append(
            Scenario(
                name=name,
                description=raw.get("description", ""),
                lanes=tuple(lanes_raw),
                port_base=port_base,
                expected_files=tuple(expected),
                config=cfg,
            )
        )
    return scenarios


def _project_config_from_dict(cfg: dict[str, Any]):
    """Build a ``ProjectConfig`` from a scenario config dict.

    Reuses :func:`forge.cli.builder._build_config` via an empty argparse
    namespace so the CLI's merge rules (config-file > default) apply —
    the runner exercises the same ingestion path a ``forge --config foo.yaml``
    invocation does.
    """
    from forge.cli.builder import _build_config  # noqa: PLC0415

    ns = argparse.Namespace()
    # Every flag the builder may introspect; set to None so the config
    # file wins uniformly.
    for attr in (
        "project_name",
        "frontend",
        "yes",
        "quiet",
        "json_output",
        "no_docker",
        "backend_port",
        "python_version",
        "features",
        "description",
        "set_options",
        "backend_language",
        "backend_name",
        "include_auth",
        "include_chat",
        "include_openapi",
        "frontend_port",
        "color_scheme",
        "author_name",
        "package_manager",
        "org_name",
        "api_base_url",
        "api_proxy_target",
        "generate_e2e_tests",
        "include_keycloak",
        "keycloak_port",
        "keycloak_realm",
        "keycloak_url",
        "node_version",
        "rust_edition",
        "output_dir",
    ):
        setattr(ns, attr, None)

    return _build_config(ns, cfg)


def run_lane_generate(scenario: Scenario) -> LaneResult:
    """Lane A: generate into a tmp dir, assert expected files exist."""
    from forge.errors import ForgeError  # noqa: PLC0415
    from forge.generator import generate  # noqa: PLC0415

    start = perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix=f"forge-matrix-{scenario.name}-"))
    try:
        cfg_copy = dict(scenario.config)
        cfg_copy["output_dir"] = str(tmp)
        try:
            project_config = _project_config_from_dict(cfg_copy)
            project_config.validate()
        except (ValueError, ForgeError) as e:
            return LaneResult(
                scenario=scenario.name,
                lane="generate",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"config build/validate failed: {e}",
            )

        try:
            project_root = generate(project_config, quiet=True, dry_run=False)
        except ForgeError as e:
            return LaneResult(
                scenario=scenario.name,
                lane="generate",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"generate raised {type(e).__name__}({e.code}): {e.message}",
            )

        missing = [f for f in scenario.expected_files if not (project_root / f).exists()]
        if missing:
            return LaneResult(
                scenario=scenario.name,
                lane="generate",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details="expected files missing",
                missing_files=missing,
            )
        return LaneResult(
            scenario=scenario.name,
            lane="generate",
            status="ok",
            duration_ms=int((perf_counter() - start) * 1000),
        )
    finally:
        # Windows can hold file handles open briefly after Copier finishes;
        # ignore_errors keeps the runner robust without leaking tmp dirs
        # in CI (they land under %TEMP% and get reaped by the OS).
        shutil.rmtree(tmp, ignore_errors=True)


def run_lane_verify(scenario: Scenario) -> LaneResult:
    """Lane B: generate, then invoke each backend's toolchain.verify().

    Keeps the generated project on disk after lane A succeeds so the
    toolchains can operate on real files, then tears it down. Surfaces
    a failed :class:`Check` as a lane-B failure with the names of the
    failing checks in ``details``.
    """
    from forge.config import BACKEND_REGISTRY  # noqa: PLC0415
    from forge.errors import ForgeError  # noqa: PLC0415
    from forge.generator import generate  # noqa: PLC0415

    start = perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix=f"forge-matrix-{scenario.name}-verify-"))
    try:
        cfg_copy = dict(scenario.config)
        cfg_copy["output_dir"] = str(tmp)
        try:
            project_config = _project_config_from_dict(cfg_copy)
            project_config.validate()
        except (ValueError, ForgeError) as e:
            return LaneResult(
                scenario=scenario.name,
                lane="verify",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"config build/validate failed: {e}",
            )
        try:
            project_root = generate(project_config, quiet=True, dry_run=False)
        except ForgeError as e:
            return LaneResult(
                scenario=scenario.name,
                lane="verify",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"generate raised {type(e).__name__}({e.code}): {e.message}",
            )

        # Drop minimal weld-* stub SDKs into <project>/sdks/ so Python
        # services' [tool.uv.sources] entries resolve. See
        # _inject_weld_stubs docstring for the rationale.
        _inject_weld_stubs(project_root)

        failures: list[str] = []
        for bc in project_config.backends:
            spec = BACKEND_REGISTRY[bc.language]
            backend_dir = project_root / "services" / bc.name
            try:
                spec.toolchain.install(backend_dir, quiet=True)
                checks = spec.toolchain.verify(backend_dir, quiet=True)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{bc.name}: toolchain raised {type(exc).__name__}: {exc}")
                continue
            for check in checks:
                if check.status == "fail":
                    failures.append(f"{bc.name}:{check.name}")

        # Frontend build check — catches vue-tsc / svelte-check / vite build
        # regressions on PR rather than waiting for nightly compose-up (lane
        # C). ``frontend_mode`` is the project-level option discriminator
        # (``options["frontend.mode"]``); ``_validate_frontend_mode_coherence``
        # already keeps it in lock-step with ``FrontendConfig.framework``.
        if project_config.frontend is not None and project_config.frontend_mode != "none":
            fe_dir = project_root / "apps" / "frontend"
            fe_result = _verify_frontend(project_config.frontend, fe_dir)
            if fe_result is not None:
                failures.append(f"frontend:{fe_result}")

        if failures:
            return LaneResult(
                scenario=scenario.name,
                lane="verify",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details="toolchain checks failed: " + "; ".join(failures),
            )
        return LaneResult(
            scenario=scenario.name,
            lane="verify",
            status="ok",
            duration_ms=int((perf_counter() - start) * 1000),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_lane_smoke(scenario: Scenario) -> LaneResult:
    """Lane C: generate, compose-up, assert contract, compose-down.

    Requires ``docker`` on PATH. Skipped (not failed) when docker is
    unavailable so developer machines without Docker don't show spurious
    failures; CI is expected to have Docker and will exercise this.
    """
    import subprocess  # noqa: PLC0415

    # ``tests.matrix.smoke_contract`` is a sibling module; when this file
    # is invoked as a script (``uv run python tests/matrix/runner.py``)
    # the script's own directory — not the repo root — is on sys.path,
    # so the absolute ``from tests.matrix...`` import below would
    # ``ModuleNotFoundError`` on the matrix-nightly CI runner. Add the
    # repo root once, idempotently, before the absolute import.
    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    from forge.errors import ForgeError  # noqa: PLC0415
    from forge.generator import generate  # noqa: PLC0415
    from tests.matrix.smoke_contract import assert_contract  # noqa: PLC0415

    docker_exe = shutil.which("docker")
    if docker_exe is None:
        return LaneResult(
            scenario=scenario.name,
            lane="smoke",
            status="skip",
            duration_ms=0,
            details="docker not on PATH",
        )

    start = perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix=f"forge-matrix-{scenario.name}-smoke-"))
    project_root: Path | None = None
    compose_up = False
    try:
        cfg_copy = dict(scenario.config)
        cfg_copy["output_dir"] = str(tmp)
        try:
            project_config = _project_config_from_dict(cfg_copy)
            project_config.validate()
            project_root = generate(project_config, quiet=True, dry_run=False)
        except (ValueError, ForgeError) as e:
            return LaneResult(
                scenario=scenario.name,
                lane="smoke",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"generate failed: {e}",
            )

        # Drop weld-* stubs into <project>/sdks/ so Python-service Docker
        # builds (which run ``uv sync`` against the same [tool.uv.sources])
        # have something to resolve against. Same hook as the verify lane.
        _inject_weld_stubs(project_root)

        compose_file = project_root / "docker-compose.yml"
        if not compose_file.exists():
            return LaneResult(
                scenario=scenario.name,
                lane="smoke",
                status="skip",
                duration_ms=int((perf_counter() - start) * 1000),
                details="no docker-compose.yml rendered (scenario likely headless)",
            )

        # Bring up the whole stack detached. --wait blocks on each service's
        # healthcheck (or a default readiness guess) — much more reliable
        # than polling ourselves. Compose-v2 only; Compose-v1 will fail
        # and we surface it as a lane-C fail rather than try to simulate.
        up_result = subprocess.run(
            [docker_exe, "compose", "-f", str(compose_file), "up", "-d", "--wait"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if up_result.returncode != 0:
            stderr_tail = "\n".join(up_result.stderr.strip().splitlines()[-5:])
            return LaneResult(
                scenario=scenario.name,
                lane="smoke",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"docker compose up failed (exit {up_result.returncode}): {stderr_tail}",
            )
        compose_up = True

        # Run the HTTP contract against each backend.
        violations: list[str] = []
        for bc in project_config.backends:
            base_url = f"http://localhost:{bc.server_port}"
            result = assert_contract(base_url, scenario.name, bc.name)
            if not result.passed:
                violations.extend(f"{bc.name}:{v.endpoint}: {v.reason}" for v in result.violations)

        if violations:
            return LaneResult(
                scenario=scenario.name,
                lane="smoke",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details="contract violations: "
                + "; ".join(violations[:5])
                + (f" (+{len(violations) - 5} more)" if len(violations) > 5 else ""),
            )
        return LaneResult(
            scenario=scenario.name,
            lane="smoke",
            status="ok",
            duration_ms=int((perf_counter() - start) * 1000),
        )
    finally:
        if compose_up and project_root is not None:
            compose_file = project_root / "docker-compose.yml"
            # Capture compose logs + ps into FORGE_MATRIX_LOG_DIR (if set)
            # BEFORE tearing the stack down. CI jobs read these as artifact
            # input — see .github/workflows/{ci,matrix-nightly}.yml. Doing
            # it inside the runner avoids the race where a post-job step
            # tries to read /tmp dirs we've already removed.
            log_dir = os.environ.get("FORGE_MATRIX_LOG_DIR")
            if log_dir:
                _dump_compose_diagnostics(
                    docker_exe, compose_file, Path(log_dir), scenario.name
                )
            subprocess.run(
                [
                    docker_exe,
                    "compose",
                    "-f",
                    str(compose_file),
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        shutil.rmtree(tmp, ignore_errors=True)


def _dump_compose_diagnostics(
    docker_exe: str, compose_file: Path, log_dir: Path, scenario_name: str
) -> None:
    """Write ``docker compose logs`` + ``ps`` into ``log_dir`` for triage.

    Best-effort: a failure to capture must not mask the upstream lane
    failure, so all subprocesses run with ``check=False`` and short
    timeouts and any OSError on the file write is swallowed.
    """
    import subprocess  # noqa: PLC0415

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    log_path = log_dir / f"{scenario_name}.log"
    ps_path = log_dir / f"{scenario_name}.ps"
    with (
        contextlib.suppress(OSError, subprocess.TimeoutExpired),
        log_path.open("w", encoding="utf-8") as fh,
    ):
        subprocess.run(
            [docker_exe, "compose", "-f", str(compose_file), "logs", "--no-color"],
            stdout=fh,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
    with (
        contextlib.suppress(OSError, subprocess.TimeoutExpired),
        ps_path.open("w", encoding="utf-8") as fh,
    ):
        subprocess.run(
            [docker_exe, "compose", "-f", str(compose_file), "ps"],
            stdout=fh,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )


def run_lane_roundtrip(scenario: Scenario) -> LaneResult:
    """Lane D: bidirectional round-trip CI gate (Phase 5/6).

    v2 contract — what lane D enforces today:
      1. **Generate** the scenario into ``project-a``.
      2. **FR1** — :func:`harvest_project` on the fresh project MUST
         emit zero ``"block"`` and zero ``"files"`` candidates. Lane
         D fails on a positive count; the rationale + offending
         candidates surface in ``details``.
      3. **Apply-back round-trip** — when the project ships at least
         one literal-text FORGE sentinel block, stage a synthetic edit,
         harvest, apply the bundle to the LIVE forge tree (with
         snapshot+restore in ``finally`` so other parallel lanes don't
         see polluted fragments), regenerate into ``project-b``, and
         assert that the two project trees match modulo documented
         noise (emitted_at timestamps, sentinel fingerprints, manifest
         sha256 fields, .git/, .copier-answers.yml).
      4. **Vacuously-true scenarios** — projects without any literal
         sentinel block (no Jinja-free apply-back-capable site) land
         as ``ok`` with a note. The round-trip contract is empty for
         block-less scenarios.

    Lane D opts in per-scenario via ``scenarios.yaml``. Nightly CI
    runs the opted-in set; PR CI doesn't touch this lane unless a
    contributor explicitly invokes it (``--scenario X --lane roundtrip``).
    """
    from forge.errors import ForgeError  # noqa: PLC0415
    from forge.generator import generate  # noqa: PLC0415
    from forge.sync.project_to_forge import (  # noqa: PLC0415
        apply_bundle_to_fragments,
        harvest_project,
    )

    start = perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix=f"forge-matrix-{scenario.name}-roundtrip-"))
    try:
        cfg_copy = dict(scenario.config)
        cfg_copy["output_dir"] = str(tmp / "project-a")
        try:
            project_config = _project_config_from_dict(cfg_copy)
            project_config.validate()
            project_a = generate(project_config, quiet=True, dry_run=False)
        except (ValueError, ForgeError) as e:
            return LaneResult(
                scenario=scenario.name,
                lane="roundtrip",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=f"first generate failed: {e}",
            )

        # FR1 — fresh-generate harvest must produce zero block/files
        # candidates. ``deps`` + ``env`` legitimately surface base-
        # template names that no fragment claims; scope the assertion
        # to the kinds that ``apply_bundle_to_fragments`` covers.
        bundle_pre = harvest_project(project_a, quiet=True)
        fr1_offenders = [c for c in bundle_pre.candidates if c.kind in ("block", "files")]
        if fr1_offenders:
            return LaneResult(
                scenario=scenario.name,
                lane="roundtrip",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details=(
                    f"FR1 violation: fresh-generate produced "
                    f"{len(fr1_offenders)} block/files candidate(s); "
                    f"first: {fr1_offenders[0].fragment}/{fr1_offenders[0].rel_path}"
                ),
            )

        # Edit a non-Jinja sentinel block (apply-back literalizes the
        # user's body; Jinja-bearing blocks round-trip incorrectly and
        # are flagged needs-review at harvest anyway).
        edited_path = _edit_one_literal_block(project_a)
        if edited_path is None:
            return LaneResult(
                scenario=scenario.name,
                lane="roundtrip",
                status="ok",
                duration_ms=int((perf_counter() - start) * 1000),
                details=(
                    "FR1 passed; no literal FORGE sentinel block to exercise "
                    "the apply-back round-trip (vacuously round-trippable)"
                ),
            )

        # Harvest the user-edit. Filter to block candidates only —
        # deps/env are legitimately deferred (not part of FR2's
        # contract).
        bundle_post = harvest_project(project_a, quiet=True)
        bundle_post.candidates[:] = [c for c in bundle_post.candidates if c.kind == "block"]
        if not any(c.risk == "safe-apply" for c in bundle_post.candidates):
            return LaneResult(
                scenario=scenario.name,
                lane="roundtrip",
                status="ok",
                duration_ms=int((perf_counter() - start) * 1000),
                details=(
                    "FR1 passed; no safe-apply block candidate after edit "
                    "(fragment must be Jinja-templated)"
                ),
            )

        # Snapshot every inject.yaml under the live forge package, apply
        # the bundle in place, regenerate, compare, and revert in
        # ``finally``. This pattern is necessary because the generator
        # imports its fragment registry at module load; pointing it at
        # a clone would have no effect on the second generate.
        forge_repo = _live_forge_root()
        inject_yamls = list((forge_repo / "forge").rglob("inject.yaml"))
        snapshots = {p: p.read_bytes() for p in inject_yamls}
        try:
            report = apply_bundle_to_fragments(bundle_post, forge_repo, quiet=True)
            if report.errored:
                first_err = next((e.error for e in report.entries if e.status == "errored"), "")
                return LaneResult(
                    scenario=scenario.name,
                    lane="roundtrip",
                    status="fail",
                    duration_ms=int((perf_counter() - start) * 1000),
                    details=(
                        f"apply-back errored on {report.errored} block "
                        f"candidate(s); first: {first_err}"
                    ),
                )

            cfg_b = dict(scenario.config)
            cfg_b["output_dir"] = str(tmp / "project-b")
            try:
                project_config_b = _project_config_from_dict(cfg_b)
                project_config_b.validate()
                project_b = generate(project_config_b, quiet=True, dry_run=False)
            except (ValueError, ForgeError) as e:
                return LaneResult(
                    scenario=scenario.name,
                    lane="roundtrip",
                    status="fail",
                    duration_ms=int((perf_counter() - start) * 1000),
                    details=f"second generate failed: {e}",
                )

            differing = _diff_project_trees_normalized(project_a, project_b)
            if differing:
                return LaneResult(
                    scenario=scenario.name,
                    lane="roundtrip",
                    status="fail",
                    duration_ms=int((perf_counter() - start) * 1000),
                    details=(
                        f"project_a vs project_b: {len(differing)} file(s) "
                        f"differ after normalisation; first: {differing[0]}"
                    ),
                )
        finally:
            # Best-effort restore — if a snapshot path disappeared (apply-
            # back wrote elsewhere) we don't want to mask the original lane
            # failure with a teardown OSError.
            for path, content in snapshots.items():
                with contextlib.suppress(OSError):
                    path.write_bytes(content)

        return LaneResult(
            scenario=scenario.name,
            lane="roundtrip",
            status="ok",
            duration_ms=int((perf_counter() - start) * 1000),
            details=(
                f"FR1 passed; FR2 round-trip passed (applied={report.applied} block candidate(s))"
            ),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _edit_one_literal_block(project_root: Path) -> Path | None:
    """Inject a synthetic edit inside the first NON-JINJA FORGE block found.

    Walks ``project_root`` for a text file containing a ``FORGE:BEGIN``
    / ``FORGE:END`` pair whose body has no ``{{ }}`` / ``{% %}`` tokens
    (Jinja-bearing blocks round-trip incorrectly through apply-back —
    they'd re-render to a different body on the second generate, and
    the harvest already filters them to ``needs-review`` so they
    wouldn't apply under the default risk filter anyway). Inserts a
    comment line at the START of the block body and returns the edited
    path. ``None`` when no eligible block is found.
    """
    for ext in (".py", ".ts", ".js", ".rs"):
        for path in sorted(project_root.rglob(f"*{ext}")):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            idx_begin = text.find("FORGE:BEGIN ")
            idx_end = text.find("FORGE:END ")
            if idx_begin == -1 or idx_end == -1 or idx_end <= idx_begin:
                continue

            begin_line_end = text.find("\n", idx_begin)
            if begin_line_end == -1:
                continue
            body_start = begin_line_end + 1
            end_line_start = text.rfind("\n", 0, idx_end) + 1
            body = text[body_start:end_line_start]

            # Skip blocks with Jinja syntax — apply-back literalizes
            # the body and round-trip would diverge on the second
            # generate's re-render.
            if "{{" in body or "{%" in body:
                continue

            # Pick the comment prefix off the BEGIN sentinel line so
            # the injected marker matches the surrounding syntax.
            before_begin = text.rfind("\n", 0, idx_begin) + 1
            begin_line = text[before_begin:idx_begin]
            comment_prefix = begin_line.rstrip().rstrip("FORGE:").rstrip()
            if not comment_prefix:
                comment_prefix = "# "
            if not comment_prefix.endswith(" "):
                comment_prefix = comment_prefix + " "

            injection = f"{comment_prefix}forge round-trip CI marker\n"
            new_text = text[:body_start] + injection + text[body_start:]
            path.write_text(new_text, encoding="utf-8")
            return path
    return None


def _live_forge_root() -> Path:
    """Return the directory containing the live ``forge/`` package.

    Used by lane D's apply-back step to write into the live forge
    tree (with snapshot+restore in ``finally``) so a subsequent
    ``generate()`` re-emits the user's edit. The runner is invoked
    from the repo root, so the parent of this file's grand-parent
    is the directory containing ``forge/``.
    """
    return Path(__file__).resolve().parents[2]


def _diff_project_trees_normalized(a: Path, b: Path) -> list[str]:
    """Compare two project trees with the FR2-normalisation pipeline.

    Returns a sorted list of POSIX rel-paths that differ. An empty
    list means the trees match modulo:

    * ``.git/...`` — different sha objects across two ``git init`` runs.
    * ``.copier-answers.yml`` — Copier internals (``_commit`` /
      ``_src_path`` may drift).
    * ``emitted_at = "..."`` — UTC-second granularity timestamps in
      ``forge.toml`` provenance entries.
    * ``sha256 = "..."`` / ``snippet_sha256 = "..."`` — derived from
      file/snippet content; project_a's manifest was recorded before
      the user's edit (so it's stale relative to the on-disk file),
      while project_b's is fresh. The contract is about CONTENT
      equality, not manifest metadata.
    * ``fp:<hex8>`` in FORGE BEGIN sentinels — fingerprint of the
      rendered snippet; project_a has the OLD fingerprint (user only
      edited the body), project_b has the NEW one (regenerate
      re-stamps).

    LF/CRLF normalization is applied to every text file so the
    comparison is platform-tolerant.
    """
    import re  # noqa: PLC0415

    def is_excluded(rel: str) -> bool:
        if rel.startswith(".git/") or "/.git/" in rel or rel == ".git":
            return True
        return rel.endswith(".copier-answers.yml")

    def normalize(rel: str, text: str) -> str:
        out = text
        if rel.endswith("forge.toml"):
            out = re.sub(r'emitted_at\s*=\s*"[^"]*"', 'emitted_at = "<NORM>"', out)
            out = re.sub(r'sha256\s*=\s*"[0-9a-f]+"', 'sha256 = "<NORM>"', out)
            out = re.sub(
                r'snippet_sha256\s*=\s*"[0-9a-f]+"',
                'snippet_sha256 = "<NORM>"',
                out,
            )
        out = re.sub(r"FORGE:BEGIN ([^\n]*?) fp:[0-9a-f]{8}", r"FORGE:BEGIN \1 fp:<NORM>", out)
        return out

    def is_text_bytes(data: bytes) -> bool:
        if b"\x00" in data[:8192]:
            return False
        try:
            data[:8192].decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    files_a = {
        p.relative_to(a).as_posix(): p
        for p in a.rglob("*")
        if p.is_file() and not is_excluded(p.relative_to(a).as_posix())
    }
    files_b = {
        p.relative_to(b).as_posix(): p
        for p in b.rglob("*")
        if p.is_file() and not is_excluded(p.relative_to(b).as_posix())
    }

    differing: list[str] = []
    for rel in sorted(set(files_a) | set(files_b)):
        pa = files_a.get(rel)
        pb = files_b.get(rel)
        if pa is None or pb is None:
            differing.append(rel)
            continue
        ba = pa.read_bytes()
        bb = pb.read_bytes()
        if ba == bb:
            continue
        if not (is_text_bytes(ba) and is_text_bytes(bb)):
            differing.append(rel)
            continue
        sa = normalize(rel, ba.decode("utf-8", errors="replace"))
        sb = normalize(rel, bb.decode("utf-8", errors="replace"))
        if sa == sb or sa.replace("\r\n", "\n") == sb.replace("\r\n", "\n"):
            continue
        differing.append(rel)
    return differing


def run_lane_update(scenario: Scenario) -> LaneResult:
    """Lane E: generate, edit, run forge --update for each mode, verify outcome.

    Drives the three merge modes (``merge`` / ``skip`` / ``overwrite``)
    against an edited file in a fragment-managed zone, then runs
    ``forge --harvest --harvest-out=-`` once and asserts a parseable
    JSON bundle is emitted on stdout. Delegates the per-mode contract
    to :mod:`tests.matrix.update_contract`.

    Unlike lane D (which uses the Python API directly), lane E shells
    out to ``python -m forge`` so the argparse, builder and dispatcher
    path real users hit is exercised end-to-end on every nightly run.
    """
    # When the runner is invoked as a script (``uv run python
    # tests/matrix/runner.py``), only the script directory lands on
    # sys.path — the absolute ``from tests.matrix.update_contract``
    # import below would ``ModuleNotFoundError``. Add the repo root
    # once, idempotently, before the absolute import. Same pattern as
    # ``run_lane_smoke``.
    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    from tests.matrix.update_contract import run_update_contract  # noqa: PLC0415

    return run_update_contract(scenario, _project_config_from_dict, _inject_weld_stubs)


LANE_DISPATCH = {
    "generate": run_lane_generate,
    "verify": run_lane_verify,
    "smoke": run_lane_smoke,
    "roundtrip": run_lane_roundtrip,
    "update": run_lane_update,
}


def run_scenario(scenario: Scenario, lane: Lane) -> LaneResult:
    if lane not in scenario.lanes:
        return LaneResult(
            scenario=scenario.name,
            lane=lane,
            status="skip",
            duration_ms=0,
            details=f"scenario does not opt into lane {lane}",
        )
    return LANE_DISPATCH[lane](scenario)


def _format_row(r: LaneResult) -> str:
    badge = {"ok": "OK  ", "fail": "FAIL", "skip": "SKIP"}.get(r.status, "????")
    base = f"[{badge}] {r.scenario:24s} {r.lane:8s} {r.duration_ms:>6d}ms"
    if r.status == "fail":
        return f"{base}  {r.details}" + (
            f" (missing: {', '.join(r.missing_files)})" if r.missing_files else ""
        )
    if r.status == "skip" and r.details:
        return f"{base}  ({r.details})"
    return base


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="forge config-matrix validation runner")
    parser.add_argument("--all", action="store_true", help="run every scenario")
    parser.add_argument("--scenario", help="run a single scenario by name")
    parser.add_argument(
        "--lane",
        choices=list(ALL_LANES),
        default="generate",
        help="which lane to run (default: generate)",
    )
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON results to stdout (for CI matrix aggregation)",
    )
    parser.add_argument(
        "--report",
        choices=["text", "markdown"],
        default="text",
        help=(
            "output format. 'text' is the human-readable table (default); "
            "'markdown' emits a 3-column scenario x lane grid suitable for "
            "committing to docs/matrix-status.md"
        ),
    )
    return parser.parse_args()


def _format_markdown_grid(results: list[LaneResult], scenarios: list[Scenario]) -> str:
    """Render a scenarios × lanes grid as a GitHub-flavored Markdown table.

    Exactly one cell per (scenario, lane). Statuses use simple glyphs so
    the rendered output works in the monospace GitHub UI without
    depending on emoji availability.
    """
    glyph = {"ok": "[OK  ]", "fail": "[FAIL]", "skip": "[SKIP]"}
    # Group results by scenario for O(1) lookup during render.
    by_scenario: dict[str, dict[Lane, LaneResult]] = {}
    for r in results:
        by_scenario.setdefault(r.scenario, {})[r.lane] = r  # type: ignore[index]

    lanes_in_order: tuple[Lane, ...] = ALL_LANES
    lines = [
        "| Scenario | " + " | ".join(lane for lane in lanes_in_order) + " | Notes |",
        "| " + " | ".join(["---"] * (2 + len(lanes_in_order))) + " |",
    ]
    for sc in scenarios:
        row_cells = [sc.name]
        notes_bits: list[str] = []
        for lane in lanes_in_order:
            r = by_scenario.get(sc.name, {}).get(lane)
            if r is None:
                row_cells.append("[—]")
                continue
            row_cells.append(glyph.get(r.status, "[?]"))
            if r.status == "fail" and r.details:
                notes_bits.append(f"{lane}: {r.details[:80]}")
        row_cells.append("; ".join(notes_bits) if notes_bits else "—")
        lines.append("| " + " | ".join(row_cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    try:
        scenarios = load_scenarios()
    except ValueError as e:
        print(f"scenarios.yaml is invalid: {e}", file=sys.stderr)
        return 3

    if args.list:
        print(f"{'Name':<24s} {'Lanes':<30s} {'Ports':<10s}  Description")
        for sc in scenarios:
            print(
                f"{sc.name:<24s} {','.join(sc.lanes):<30s} "
                f"{sc.port_base}-{sc.port_base + 9:<5d} {sc.description}"
            )
        return 0

    if args.scenario:
        picked = [sc for sc in scenarios if sc.name == args.scenario]
        if not picked:
            print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
            return 3
        selected = picked
    elif args.all:
        selected = scenarios
    else:
        print("Specify --all, --scenario NAME, or --list", file=sys.stderr)
        return 3

    results = [run_scenario(sc, args.lane) for sc in selected]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "scenario": r.scenario,
                        "lane": r.lane,
                        "status": r.status,
                        "duration_ms": r.duration_ms,
                        "details": r.details,
                        "missing_files": r.missing_files,
                    }
                    for r in results
                ],
                indent=2,
            )
        )
    elif args.report == "markdown":
        print(_format_markdown_grid(results, selected))
    else:
        for r in results:
            print(_format_row(r))

    failed = [r for r in results if r.status == "fail"]
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
