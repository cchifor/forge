"""Theme 1A — fingerprint parity across the three canvas lint implementations.

The canvas runtime lint lives in three hand-synchronized files:

* ``packages/canvas-vue/src/lint.ts``
* ``packages/canvas-svelte/src/lint.ts`` (header says verbatim
  "Mirrors packages/canvas-vue/src/lint.ts — keep them in sync")
* ``packages/forge-canvas-dart/lib/src/lint.dart``

Each implements the same shallow JSON-Schema lint of canvas component
props (``properties``/``required``/``additionalProperties``/``type``/
``enum``) and each short-circuits in production. The risk this test
pins: a future fix landing in one file but not the other two silently
breaks the polyglot contract.

Approach — extract a **semantic fingerprint** from each file by
regex/string-set scanning (NOT AST; an AST fingerprint would itself be a
hand-synced artifact). Compared dimensions: schema keys consumed,
``type`` branches dispatched on, normalized error-message templates,
production short-circuit presence, and the ``[forge:canvas]`` banner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LINT_FILES = {
    "vue": _REPO_ROOT / "packages" / "canvas-vue" / "src" / "lint.ts",
    "svelte": _REPO_ROOT / "packages" / "canvas-svelte" / "src" / "lint.ts",
    "dart": _REPO_ROOT / "packages" / "forge-canvas-dart" / "lib" / "src" / "lint.dart",
}

_SCHEMA_KEYS = frozenset({"properties", "required", "additionalProperties", "type", "enum"})
_TYPE_BRANCHES = frozenset({"string", "integer", "number", "boolean", "array", "object"})
# Language-specific interpolation (``${typeof value}`` / ``$value.runtimeType``
# / ``${JSON.stringify(enumValues)}``) is normalized to ``{}`` so the
# template set compares structurally, not lexically.
_CANONICAL_MESSAGES = frozenset(
    {
        "required prop is missing",
        "unknown prop",
        "expected string, got {}",
        "expected integer, got {}",
        "expected number, got {}",
        "expected boolean, got {}",
        "expected array, got {}",
        "expected object, got {}",
        "not in enum {}",
    }
)
_BANNER = "[forge:canvas]"


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_INTERP_BRACED = re.compile(r"\$\{[^}]*\}")
_INTERP_BARE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# Single / double / backtick literals. Comments must be stripped first so
# commentary apostrophes (``don't``) don't kick the scanner into a
# multi-line slurp that swallows the next quote.
_QUOTED = re.compile(
    r"""'(?P<single>(?:\\.|[^'\\])*)'
       |"(?P<double>(?:\\.|[^"\\])*)"
       |`(?P<backtick>(?:\\.|[^`\\])*)`""",
    re.VERBOSE | re.DOTALL,
)


def _strip_comments(source: str) -> str:
    return _BLOCK_COMMENT.sub("", _LINE_COMMENT.sub("", source))


def _extract_literals(source: str) -> list[str]:
    out: list[str] = []
    for m in _QUOTED.finditer(_strip_comments(source)):
        for key in ("single", "double", "backtick"):
            s = m.group(key)
            if s is not None:
                out.append(s)
                break
    return out


def _normalize_message(raw: str) -> str:
    """Collapse language-specific interpolation to a ``{}`` placeholder."""
    return _INTERP_BARE.sub("{}", _INTERP_BRACED.sub("{}", raw)).strip()


def _has_schema_key(source: str, key: str) -> bool:
    """Detect a read of JSON-Schema field ``key`` in either spelling.

    TS uses dotted access (``propsSchema.properties``), Dart uses quoted
    subscripts (``propsSchema['properties']``). Both count.
    """
    stripped = _strip_comments(source)
    dotted = re.compile(rf"\.{re.escape(key)}\b")
    subscript = re.compile(rf"""\[\s*['"]{re.escape(key)}['"]\s*\]""")
    return bool(dotted.search(stripped) or subscript.search(stripped))


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LintFingerprint:
    label: str
    path: Path
    schema_keys: frozenset[str] = field(default_factory=frozenset)
    type_branches: frozenset[str] = field(default_factory=frozenset)
    messages: frozenset[str] = field(default_factory=frozenset)
    has_prod_gate: bool = False
    has_banner: bool = False

    def comparable(self) -> tuple:
        return (
            self.schema_keys,
            self.type_branches,
            self.messages,
            self.has_prod_gate,
            self.has_banner,
        )

    def diff_against(self, other: LintFingerprint) -> list[str]:
        """Human-readable diff of parity-bearing fields. Empty == equal."""
        diffs: list[str] = []
        for attr in ("schema_keys", "type_branches", "messages"):
            mine: frozenset[str] = getattr(self, attr)
            theirs: frozenset[str] = getattr(other, attr)
            if mine != theirs:
                only_self = sorted(mine - theirs)
                only_other = sorted(theirs - mine)
                diffs.append(
                    f"{attr}: {self.label} has {only_self!r} that "
                    f"{other.label} lacks; {other.label} has "
                    f"{only_other!r} that {self.label} lacks"
                )
        for attr in ("has_prod_gate", "has_banner"):
            if getattr(self, attr) != getattr(other, attr):
                diffs.append(
                    f"{attr}: {self.label}={getattr(self, attr)} vs "
                    f"{other.label}={getattr(other, attr)}"
                )
        return diffs


def _fingerprint(label: str, path: Path) -> LintFingerprint:
    source = path.read_text(encoding="utf-8")
    literals = _extract_literals(source)
    literal_set = set(literals)
    return LintFingerprint(
        label=label,
        path=path,
        schema_keys=frozenset(k for k in _SCHEMA_KEYS if _has_schema_key(source, k)),
        type_branches=frozenset(t for t in _TYPE_BRANCHES if t in literal_set),
        messages=frozenset(
            n for raw in literals if (n := _normalize_message(raw)) in _CANONICAL_MESSAGES
        ),
        # Vite-style PROD gate, Node-style NODE_ENV gate, or Flutter
        # kReleaseMode. The two TS files use the first two; the Dart file
        # uses the third.
        has_prod_gate=(
            ("import.meta" in source and "PROD" in source)
            or ("process.env" in source and "NODE_ENV" in source)
            or "kReleaseMode" in source
        ),
        has_banner=any(_BANNER in lit for lit in literals),
    )


# ---------------------------------------------------------------------------
# Fixtures + tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fingerprints() -> dict[str, LintFingerprint]:
    return {label: _fingerprint(label, path) for label, path in _LINT_FILES.items()}


@pytest.mark.parametrize("label", sorted(_LINT_FILES))
def test_lint_file_exists(label: str) -> None:
    """Each fingerprinted file actually exists on disk."""
    assert _LINT_FILES[label].is_file(), f"missing {_LINT_FILES[label]}"


@pytest.mark.parametrize("label", sorted(_LINT_FILES))
def test_fingerprint_has_canonical_rule_set(
    label: str, fingerprints: dict[str, LintFingerprint]
) -> None:
    """Each file independently implements the full canonical rule set.

    Without this check the pairwise parity assertions below would still
    pass if all three files simultaneously dropped the same rule (e.g.
    nobody implements ``enum`` anymore).
    """
    fp = fingerprints[label]
    assert fp.schema_keys == _SCHEMA_KEYS, (
        f"{label} schema_keys: missing {sorted(_SCHEMA_KEYS - fp.schema_keys)!r}"
    )
    assert fp.type_branches == _TYPE_BRANCHES, (
        f"{label} type_branches: missing {sorted(_TYPE_BRANCHES - fp.type_branches)!r}"
    )
    assert fp.messages == _CANONICAL_MESSAGES, (
        f"{label} messages: missing {sorted(_CANONICAL_MESSAGES - fp.messages)!r}"
    )
    assert fp.has_prod_gate, f"{label} is missing its production short-circuit"
    assert fp.has_banner, f"{label} is missing the '[forge:canvas]' banner"


@pytest.mark.parametrize(
    ("left", "right"),
    [("vue", "svelte"), ("vue", "dart"), ("svelte", "dart")],
)
def test_fingerprints_match(
    left: str, right: str, fingerprints: dict[str, LintFingerprint]
) -> None:
    """Pairwise parity across the three implementations.

    Core drift detector — if a future commit edits one file without the
    other two, the assertion surfaces a precise diff naming the dimension
    and the two files that disagree.
    """
    diffs = fingerprints[left].diff_against(fingerprints[right])
    assert not diffs, f"{left} <-> {right} drift:\n  " + "\n  ".join(diffs)


def test_all_three_fingerprints_identical(
    fingerprints: dict[str, LintFingerprint],
) -> None:
    """Three-way identity check — single failure line on opposing drift.

    Pairwise equality is transitive, so this is technically redundant.
    Kept as a belt-and-braces guard: on the rare case where two files
    drift in opposite directions, the set-cardinality view is the
    clearest signal in the failure report.
    """
    unique = {fp.comparable() for fp in fingerprints.values()}
    assert len(unique) == 1, (
        f"lint implementations diverge: {len(unique)} unique fingerprints "
        f"across {sorted(fingerprints)}"
    )
