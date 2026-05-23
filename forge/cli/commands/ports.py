"""``forge --ports-validate`` — compile every port `.tsp` contract for CI confidence.

Walks `forge/templates/_shared/ports/` for `contract.tsp` files and shells
each out to ``npx -y @typespec/compiler --emit @typespec/openapi3``. Per-
port verdicts are printed as ``VALID`` / ``INVALID``; exit code is 0 when
every contract compiles, 1 when any fail.

Node is intentionally NOT a hard forge dependency — when ``npx`` is
absent from ``$PATH`` the command prints a one-line skip notice and
exits 0. CI environments that want validation coverage must provision
node alongside python (e.g. ``actions/setup-node`` in GitHub Actions).

This is plan Pillar D point 1 of the forge improvement roadmap (RFC-005
reduced-scope path). The contracts themselves are spec-only; no code is
generated from them today. See ``forge/templates/_shared/ports/README.md``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _PortResult:
    """One port's validation outcome — what the dispatcher prints + returns."""

    name: str
    contract: Path
    valid: bool
    error: str = ""


# Exit code returned when at least one contract fails to compile. Sits
# alongside the broader CLI exit-code taxonomy in ``forge.errors``; 1 is
# the generic "command failed" code used by the existing canvas / verify
# verbs for their own non-fatal failure paths.
_EXIT_INVALID_CONTRACT = 1


def _ports_root() -> Path:
    """Return the on-disk path to the ``_shared/ports/`` template directory.

    Resolved relative to the installed ``forge`` package so the verb works
    regardless of the caller's CWD (matching ``forge --list`` and friends).
    """
    return Path(__file__).resolve().parent.parent.parent / "templates" / "_shared" / "ports"


def _discover_contracts(root: Path) -> list[tuple[str, Path]]:
    """Return ``(port_name, contract_path)`` pairs for every ``contract.tsp``.

    Sorted by port name for deterministic output — keeps the verb's stdout
    diff-stable when callers pipe it to ``grep`` or ``jq``.
    """
    if not root.is_dir():
        return []
    contracts = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        contract = sub / "contract.tsp"
        if contract.is_file():
            contracts.append((sub.name, contract))
    return contracts


def _npx_available() -> bool:
    """True iff ``npx`` is discoverable on ``$PATH``.

    Wrapped in a helper so tests can monkeypatch it without juggling the
    real ``PATH`` env var.
    """
    return shutil.which("npx") is not None


def _compile_one(contract: Path) -> _PortResult:
    """Compile one ``contract.tsp`` via ``npx -y @typespec/compiler``.

    Returns a :class:`_PortResult` capturing the verdict. Never raises —
    subprocess failures (compiler bug, network outage, etc.) surface as
    ``valid=False`` with the stderr text attached so the dispatcher can
    render them. Compiler output is emitted to a per-call tempdir so we
    do not litter the repo with generated OpenAPI documents.
    """
    port_name = contract.parent.name
    with tempfile.TemporaryDirectory(prefix="forge-ports-validate-") as tmpdir:
        cmd = [
            "npx",
            "-y",
            "@typespec/compiler",
            "compile",
            str(contract),
            "--emit",
            "@typespec/openapi3",
            "--output-dir",
            tmpdir,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return _PortResult(
                name=port_name,
                contract=contract,
                valid=False,
                error="npx tsp compile timed out after 180s",
            )
        except FileNotFoundError:
            # npx vanished between the up-front check and the actual call.
            return _PortResult(
                name=port_name,
                contract=contract,
                valid=False,
                error="npx not found on PATH",
            )

    if proc.returncode == 0:
        return _PortResult(name=port_name, contract=contract, valid=True)
    err = (proc.stderr or proc.stdout or "").strip()
    return _PortResult(
        name=port_name,
        contract=contract,
        valid=False,
        error=err or f"npx exited {proc.returncode}",
    )


def _run_ports_validate(args: argparse.Namespace) -> int:
    """Dispatcher for ``forge --ports-validate``. Returns the exit code.

    Three terminal paths:
      * no contracts on disk → exit 0 with a warning (lets a partially
        installed forge — or one mid-refactor — fail soft).
      * ``npx`` missing → exit 0 with a skip notice (node is optional).
      * one or more contracts INVALID → exit ``_EXIT_INVALID_CONTRACT``.

    ``--json`` callers receive a single JSON object on stdout with a
    ``results`` array; text callers see one ``<port> <verdict>`` line per
    contract with INVALID rows followed by the compiler's stderr.
    """
    json_output = bool(getattr(args, "json_output", False))
    root = _ports_root()
    contracts = _discover_contracts(root)

    if not contracts:
        msg = f"no contract.tsp files found under {root}"
        if json_output:
            sys.stdout.write(json.dumps({"warning": msg, "results": []}) + "\n")
        else:
            sys.stderr.write(f"forge --ports-validate: {msg}\n")
        return 0

    if not _npx_available():
        msg = (
            "npx not found on PATH; skipping TypeSpec compilation. "
            "Install Node.js (>=18) to enable contract validation."
        )
        if json_output:
            sys.stdout.write(
                json.dumps(
                    {
                        "skipped": True,
                        "reason": msg,
                        "ports": [name for name, _ in contracts],
                    }
                )
                + "\n"
            )
        else:
            sys.stderr.write(f"forge --ports-validate: {msg}\n")
            for name, _ in contracts:
                sys.stderr.write(f"  {name} SKIPPED\n")
        return 0

    results = [_compile_one(path) for _, path in contracts]

    if json_output:
        payload = {
            "results": [
                {
                    "port": r.name,
                    "contract": str(r.contract),
                    "valid": r.valid,
                    "error": r.error,
                }
                for r in results
            ],
        }
        sys.stdout.write(json.dumps(payload) + "\n")
    else:
        # Pad the port name column so the verdict column lines up — keeps
        # the human reading the table from squinting.
        width = max((len(r.name) for r in results), default=0)
        for r in results:
            verdict = "VALID" if r.valid else "INVALID"
            sys.stdout.write(f"{r.name.ljust(width)}  {verdict}\n")
            if not r.valid and r.error:
                for line in r.error.splitlines():
                    sys.stdout.write(f"    {line}\n")

    return 0 if all(r.valid for r in results) else _EXIT_INVALID_CONTRACT
