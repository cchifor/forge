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

CLI usage (from the repo root)::

    uv run python tests/matrix/runner.py --all                 # all scenarios, lane A
    uv run python tests/matrix/runner.py --scenario py_vue_full
    uv run python tests/matrix/runner.py --list                # list scenarios + lanes
    uv run python tests/matrix/runner.py --all --lane generate # explicit lane

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
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import yaml

Lane = Literal["generate", "verify", "smoke"]
ALL_LANES: tuple[Lane, ...] = ("generate", "verify", "smoke")

SCENARIOS_YAML = Path(__file__).parent / "scenarios.yaml"


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
                    f"scenario {name!r} has unknown lane {lane!r}; "
                    f"expected one of {ALL_LANES}"
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
                violations.extend(
                    f"{bc.name}:{v.endpoint}: {v.reason}" for v in result.violations
                )

        if violations:
            return LaneResult(
                scenario=scenario.name,
                lane="smoke",
                status="fail",
                duration_ms=int((perf_counter() - start) * 1000),
                details="contract violations: " + "; ".join(violations[:5])
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


LANE_DISPATCH = {
    "generate": run_lane_generate,
    "verify": run_lane_verify,
    "smoke": run_lane_smoke,
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
