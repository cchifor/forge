"""Tests for the tree-sitter-rust path of :mod:`forge.codegen.literal_finder`.

v2 Theme 3B wires :mod:`tree_sitter_rust` into the literal finder so Axum
(and any other Rust target) participates in option-promotion suggestions.
These tests pin the new contract:

* Pure literal swaps (``int`` / ``float`` / ``str`` / ``bool``) produce
  one :class:`LiteralEdit` per changed leaf.
* Raw strings round-trip through the same ``kind="str"`` channel as
  regular strings — the bundle writer doesn't need to disambiguate.
* Multi-literal swaps preserve source order in the output.
* Structural divergence (rename, added statement) returns ``()``.
* Malformed Rust on either side returns ``()`` rather than raising.

The Python and TypeScript paths are covered in
:mod:`tests.test_literal_finder`.
"""

from __future__ import annotations

import pytest

from forge.codegen.literal_finder import LiteralEdit, find_literal_edits


def _diff(upstream: str, current: str) -> tuple[LiteralEdit, ...]:
    """Shorthand for ``find_literal_edits(..., language="rust")``."""
    return find_literal_edits(upstream, current, language="rust")


class TestRustLiteralSwaps:
    """Pure literal-value swaps produce one :class:`LiteralEdit` per leaf."""

    def test_int_swap_emits_one_edit(self) -> None:
        upstream = "fn main() { let x: u32 = 120; }"
        current = "fn main() { let x: u32 = 60; }"
        edits = _diff(upstream, current)
        assert len(edits) == 1
        e = edits[0]
        assert isinstance(e, LiteralEdit)
        assert e.kind == "int"
        assert e.old_value == "120"
        assert e.new_value == "60"

    def test_float_swap_emits_one_edit(self) -> None:
        upstream = "fn main() { let x: f64 = 1.5; }"
        current = "fn main() { let x: f64 = 2.5; }"
        edits = _diff(upstream, current)
        assert len(edits) == 1
        assert edits[0].kind == "float"
        assert edits[0].old_value == "1.5"
        assert edits[0].new_value == "2.5"

    def test_string_swap_emits_one_edit(self) -> None:
        upstream = 'fn main() { let s = "hello"; }'
        current = 'fn main() { let s = "world"; }'
        edits = _diff(upstream, current)
        assert len(edits) == 1
        assert edits[0].kind == "str"
        # The full literal text — quotes included — is the surfaced value,
        # matching the Python ``cst.SimpleString.value`` convention.
        assert edits[0].old_value == '"hello"'
        assert edits[0].new_value == '"world"'

    def test_bool_swap_emits_one_edit(self) -> None:
        upstream = "fn main() { let b = true; }"
        current = "fn main() { let b = false; }"
        edits = _diff(upstream, current)
        assert len(edits) == 1
        assert edits[0].kind == "bool"
        assert edits[0].old_value == "true"
        assert edits[0].new_value == "false"

    def test_char_literal_swap_emits_str_kind(self) -> None:
        # The LiteralKind alias doesn't carry a dedicated ``char`` variant;
        # char literals fold into ``str`` so the downstream Option
        # declaration is a single-character string.
        upstream = "fn main() { let c = 'a'; }"
        current = "fn main() { let c = 'b'; }"
        edits = _diff(upstream, current)
        assert len(edits) == 1
        assert edits[0].kind == "str"
        assert edits[0].old_value == "'a'"
        assert edits[0].new_value == "'b'"


class TestRustRawStrings:
    """Raw string literals (``r"..."``) route through the same ``str`` channel."""

    def test_raw_string_swap_emits_str_kind(self) -> None:
        upstream = 'fn main() { let s = r"hello"; }'
        current = 'fn main() { let s = r"world"; }'
        edits = _diff(upstream, current)
        assert len(edits) == 1
        assert edits[0].kind == "str"
        assert edits[0].old_value == 'r"hello"'
        assert edits[0].new_value == 'r"world"'

    def test_raw_string_to_regular_string_is_structural(self) -> None:
        # The grammar uses different node types for raw vs cooked strings,
        # so this is a structural divergence — not a literal swap.
        upstream = 'fn main() { let s = r"hello"; }'
        current = 'fn main() { let s = "hello"; }'
        assert _diff(upstream, current) == ()


class TestRustMultiLiteral:
    """Three literals in source order produce three records in source order."""

    def test_three_literals_preserve_order(self) -> None:
        upstream = 'fn config() {\n    let a = 1;\n    let b = "alpha";\n    let c = true;\n}\n'
        current = 'fn config() {\n    let a = 2;\n    let b = "beta";\n    let c = false;\n}\n'
        edits = _diff(upstream, current)
        assert len(edits) == 3
        assert [e.kind for e in edits] == ["int", "str", "bool"]
        assert [e.old_value for e in edits] == ["1", '"alpha"', "true"]
        assert [e.new_value for e in edits] == ["2", '"beta"', "false"]
        # Line numbers are 1-indexed and follow source order.
        assert [e.line for e in edits] == [2, 3, 4]


class TestRustStructuralFingerprint:
    """Structurally-identical functions with different literals fingerprint identically.

    The finder doesn't expose a public fingerprint API, but the
    behavioural contract is equivalent: two bodies that differ ONLY in
    literal values produce a non-empty edit list (i.e. the structural
    walk succeeded), while bodies that diverge in identifier names
    return ``()``.
    """

    def test_same_structure_different_literals_succeeds(self) -> None:
        upstream = "fn timeout() -> u32 { 100 }"
        current = "fn timeout() -> u32 { 5000 }"
        edits = _diff(upstream, current)
        assert len(edits) == 1
        assert edits[0].kind == "int"

    def test_renamed_function_is_structural(self) -> None:
        # Identifier change at a structurally-equivalent position bails
        # the parallel walk — exactly mirrors the Python finder's
        # rename-as-structural rule.
        upstream = "fn timeout() -> u32 { 100 }"
        current = "fn deadline() -> u32 { 100 }"
        assert _diff(upstream, current) == ()

    def test_added_statement_is_structural(self) -> None:
        upstream = "fn main() { let x = 1; }"
        current = "fn main() { let x = 1; let y = 2; }"
        assert _diff(upstream, current) == ()


class TestRustParseFailures:
    """Malformed Rust on either side returns ``()`` rather than crashing."""

    def test_malformed_current_returns_empty(self) -> None:
        upstream = "fn main() { let x = 1; }"
        current = "fn main() { let x = ###; }"
        assert _diff(upstream, current) == ()

    def test_malformed_upstream_returns_empty(self) -> None:
        upstream = "fn main() { let x = ###; }"
        current = "fn main() { let x = 1; }"
        assert _diff(upstream, current) == ()

    def test_malformed_does_not_raise(self) -> None:
        # Defensive — the contract is "return ()", not "propagate". A
        # raised exception here would crash the harvester at scan time.
        try:
            _diff("garbage {{{ }}}", "more garbage")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"finder raised on malformed input: {exc!r}")


class TestRustNoChangeShortCircuit:
    """Byte-identical bodies short-circuit before the parser is invoked."""

    def test_identical_bodies_return_empty(self) -> None:
        body = "fn main() { let x = 1; }"
        assert _diff(body, body) == ()
