"""Tests for the TypeSpec port contracts shipped under ``forge/templates/_shared/ports/``.

These contracts are spec-only — no code is generated from them today (see
``forge/templates/_shared/ports/README.md``). The tests in this module
assert four things:

    * Every plan-mentioned port (queue, object_store, llm, vector_store)
      has a ``contract.tsp`` on disk.
    * Each contract carries the structural TypeSpec keywords the spec
      requires (``namespace`` + at least one ``interface`` + at least one
      ``op`` declared via ``op``-syntax or interface body).
    * The ``forge --ports-validate`` flag is wired into the CLI parser.
    * When ``npx`` is missing the dispatcher exits 0 with a SKIPPED row,
      so CI without node still passes.

Compiling the contracts through the real ``npx -y @typespec/compiler``
is intentionally NOT exercised here — it would force every contributor's
local test loop to either install node + the TypeSpec compiler or
tolerate a flaky network round-trip. The CLI command remains the
opt-in path for full compiler validation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.cli.commands.ports import (
    _discover_contracts,
    _PortResult,
    _ports_root,
    _run_ports_validate,
)
from forge.cli.parser import _build_parser

# ---------------------------------------------------------------------------
# Expected port set — the four ports RFC-005 § "Port Contracts" enumerates
# and the plan Pillar D point 1 names. Drift here means the contracts on
# disk no longer match the plan; flag it loudly.
# ---------------------------------------------------------------------------


_EXPECTED_PORTS = {"queue", "object_store", "llm", "vector_store"}


# ---------------------------------------------------------------------------
# Contract-file existence + content shape
# ---------------------------------------------------------------------------


class TestContractFilesExist:
    """Every plan-mentioned port has a ``contract.tsp`` on disk."""

    def test_ports_root_exists(self) -> None:
        root = _ports_root()
        assert root.is_dir(), f"expected {root} to be a directory"

    def test_every_expected_port_has_contract(self) -> None:
        root = _ports_root()
        missing = {p for p in _EXPECTED_PORTS if not (root / p / "contract.tsp").is_file()}
        assert not missing, f"missing contract.tsp for: {missing}"

    def test_no_unexpected_ports(self) -> None:
        # If someone adds a fifth port without updating _EXPECTED_PORTS
        # here AND in plan Pillar D, the contract has drifted from the
        # plan. Catch the drift early.
        root = _ports_root()
        on_disk = {p for p, _ in _discover_contracts(root)}
        unexpected = on_disk - _EXPECTED_PORTS
        assert not unexpected, (
            f"unexpected ports on disk: {unexpected} — update _EXPECTED_PORTS "
            "and the plan if this is intentional"
        )

    def test_ports_readme_present(self) -> None:
        # README explains the spec-only contract; if it vanishes the
        # plugin-author story collapses.
        readme = _ports_root() / "README.md"
        assert readme.is_file(), f"expected {readme} to exist"
        body = readme.read_text(encoding="utf-8")
        assert "TypeSpec" in body
        assert "forge --ports-validate" in body


# ---------------------------------------------------------------------------
# Per-contract structural sanity — keyword presence, not full validation
# ---------------------------------------------------------------------------


class TestContractStructure:
    """Each contract carries the structural keywords TypeSpec requires.

    Full validation is an ``npx tsp compile`` away — that lives behind
    ``forge --ports-validate`` so contributors without node can still
    run unit tests. These keyword checks are the cheap floor.
    """

    @pytest.mark.parametrize("port", sorted(_EXPECTED_PORTS))
    def test_contract_declares_namespace(self, port: str) -> None:
        body = (_ports_root() / port / "contract.tsp").read_text(encoding="utf-8")
        assert "namespace " in body, f"{port}: contract missing `namespace` declaration"

    @pytest.mark.parametrize("port", sorted(_EXPECTED_PORTS))
    def test_contract_declares_interface(self, port: str) -> None:
        body = (_ports_root() / port / "contract.tsp").read_text(encoding="utf-8")
        assert "interface " in body, f"{port}: contract missing `interface` declaration"

    @pytest.mark.parametrize("port", sorted(_EXPECTED_PORTS))
    def test_contract_declares_at_least_one_model(self, port: str) -> None:
        body = (_ports_root() / port / "contract.tsp").read_text(encoding="utf-8")
        assert "model " in body, f"{port}: contract missing any `model` declaration"

    @pytest.mark.parametrize("port", sorted(_EXPECTED_PORTS))
    def test_contract_imports_openapi3(self, port: str) -> None:
        # The ports-validate verb emits via @typespec/openapi3; the import
        # has to land in each file for the emitter to wire up.
        body = (_ports_root() / port / "contract.tsp").read_text(encoding="utf-8")
        assert "@typespec/openapi3" in body, (
            f'{port}: contract missing `import "@typespec/openapi3"`'
        )

    def test_queue_matches_rfc_005_signature(self) -> None:
        body = (_ports_root() / "queue" / "contract.tsp").read_text(encoding="utf-8")
        # RFC-005 § "Port Contracts" → queue_port lists exactly these four
        # operations. Drift here means the contract diverged from the RFC.
        for op in ("enqueue", "poll", "ack", "nack"):
            assert f"{op}(" in body, f"queue contract missing op `{op}`"

    def test_object_store_matches_rfc_005_signature(self) -> None:
        body = (_ports_root() / "object_store" / "contract.tsp").read_text(encoding="utf-8")
        for op in ("put", "get", "delete", "presignGet", "presignPut"):
            assert f"{op}(" in body, f"object_store contract missing op `{op}`"

    def test_llm_matches_rfc_005_signature(self) -> None:
        body = (_ports_root() / "llm" / "contract.tsp").read_text(encoding="utf-8")
        for op in ("complete", "embed"):
            assert f"{op}(" in body, f"llm contract missing op `{op}`"
        assert "LlmChunk" in body

    def test_vector_store_matches_rfc_005_signature(self) -> None:
        body = (_ports_root() / "vector_store" / "contract.tsp").read_text(encoding="utf-8")
        for op in ("upsert", "search", "delete"):
            assert f"{op}(" in body, f"vector_store contract missing op `{op}`"


# ---------------------------------------------------------------------------
# CLI integration — flag wired into parser + help text
# ---------------------------------------------------------------------------


class TestCliWiring:
    def test_ports_validate_flag_is_registered(self) -> None:
        parser = _build_parser()
        flags = {opt for action in parser._actions for opt in action.option_strings}
        assert "--ports-validate" in flags

    def test_ports_validate_flag_in_help(self) -> None:
        # Help text is the discovery surface — if the flag disappears
        # from `forge --help` plugin authors won't find it.
        parser = _build_parser()
        help_text = parser.format_help()
        assert "--ports-validate" in help_text

    def test_ports_validate_dest_is_consistent(self) -> None:
        # Parser stores the flag under ``args.ports_validate`` — main.py
        # dispatches on that attr name. If they drift, the verb stops
        # firing silently.
        parser = _build_parser()
        ns = parser.parse_args(["--ports-validate"])
        assert getattr(ns, "ports_validate", False) is True


# ---------------------------------------------------------------------------
# Dispatcher behavior — discover, skip-when-npx-missing, JSON shape
# ---------------------------------------------------------------------------


def _make_args(**overrides: Any) -> argparse.Namespace:
    """Build a minimal argparse Namespace mirroring the parser surface."""
    base: dict[str, Any] = {"ports_validate": True, "json_output": False}
    base.update(overrides)
    return argparse.Namespace(**base)


class TestDiscovery:
    def test_discover_contracts_finds_all_expected_ports(self) -> None:
        root = _ports_root()
        pairs = _discover_contracts(root)
        names = {name for name, _ in pairs}
        assert names == _EXPECTED_PORTS

    def test_discover_contracts_sorted_alphabetically(self) -> None:
        # Determinism matters — JSON consumers + diff tools depend on
        # stable ordering across runs.
        pairs = _discover_contracts(_ports_root())
        names = [name for name, _ in pairs]
        assert names == sorted(names)

    def test_discover_contracts_missing_root_returns_empty(self, tmp_path: Path) -> None:
        # Defensive: a partially uninstalled forge (or one mid-refactor)
        # should not crash the verb — it should fail soft.
        assert _discover_contracts(tmp_path / "does-not-exist") == []


class TestSkipsCleanlyWithoutNpx:
    """When ``npx`` is absent the verb must exit 0 with a warning."""

    def test_text_output_when_npx_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("forge.cli.commands.ports._npx_available", return_value=False):
            code = _run_ports_validate(_make_args())
        captured = capsys.readouterr()
        assert code == 0
        assert "npx not found on PATH" in captured.err
        # Every expected port is listed in the SKIPPED block so the
        # operator sees which contracts would have been validated.
        for port in _EXPECTED_PORTS:
            assert port in captured.err

    def test_json_output_when_npx_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        import json as _json

        with patch("forge.cli.commands.ports._npx_available", return_value=False):
            code = _run_ports_validate(_make_args(json_output=True))
        captured = capsys.readouterr()
        assert code == 0
        payload = _json.loads(captured.out)
        assert payload["skipped"] is True
        assert "npx not found on PATH" in payload["reason"]
        assert set(payload["ports"]) == _EXPECTED_PORTS


class TestSkipsCleanlyWithoutContracts:
    """A partially installed forge should not crash the verb."""

    def test_text_output_when_no_contracts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(
            "forge.cli.commands.ports._ports_root",
            return_value=tmp_path / "missing",
        ):
            code = _run_ports_validate(_make_args())
        captured = capsys.readouterr()
        assert code == 0
        assert "no contract.tsp files found" in captured.err


class TestDispatchExitCodes:
    """All-VALID → 0; any INVALID → 1."""

    def test_all_valid_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Stub out the real npx subprocess call: every discovered contract
        # is reported VALID. Discovery still hits the real ports root so
        # we exercise the actual file layout.
        with (
            patch("forge.cli.commands.ports._npx_available", return_value=True),
            patch(
                "forge.cli.commands.ports._compile_one",
                side_effect=lambda c: _PortResult(name=c.parent.name, contract=c, valid=True),
            ),
        ):
            code = _run_ports_validate(_make_args())
        captured = capsys.readouterr()
        assert code == 0
        for port in _EXPECTED_PORTS:
            assert port in captured.out
            assert "VALID" in captured.out

    def test_one_invalid_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        def fake_compile(contract: Path) -> _PortResult:
            name = contract.parent.name
            if name == "queue":
                return _PortResult(
                    name=name,
                    contract=contract,
                    valid=False,
                    error="syntax error at line 42",
                )
            return _PortResult(name=name, contract=contract, valid=True)

        with (
            patch("forge.cli.commands.ports._npx_available", return_value=True),
            patch("forge.cli.commands.ports._compile_one", side_effect=fake_compile),
        ):
            code = _run_ports_validate(_make_args())
        captured = capsys.readouterr()
        assert code == 1
        assert "INVALID" in captured.out
        assert "syntax error at line 42" in captured.out

    def test_json_output_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        import json as _json

        def fake_compile(contract: Path) -> _PortResult:
            return _PortResult(name=contract.parent.name, contract=contract, valid=True)

        with (
            patch("forge.cli.commands.ports._npx_available", return_value=True),
            patch("forge.cli.commands.ports._compile_one", side_effect=fake_compile),
        ):
            code = _run_ports_validate(_make_args(json_output=True))
        captured = capsys.readouterr()
        assert code == 0
        payload = _json.loads(captured.out)
        assert {r["port"] for r in payload["results"]} == _EXPECTED_PORTS
        for r in payload["results"]:
            assert r["valid"] is True
            assert r["error"] == ""
            assert r["contract"].endswith("contract.tsp")
