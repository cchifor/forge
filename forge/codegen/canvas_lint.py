"""Generate the three canvas runtime lint implementations from one source.

The canvas runtime lint lives in three target files, one per consumer
package:

    * ``packages/canvas-vue/src/lint.ts``
    * ``packages/canvas-svelte/src/lint.ts``
    * ``packages/forge-canvas-dart/lib/src/lint.dart``

Theme 1A (``tests/test_canvas_lint_parity.py``) added a fingerprint
parity test that fails when the three files drift. Theme 1C — this
module — kills the drift surface entirely by deriving all three files
from a single declarative description (``_TYPE_RULES`` below).

Run as a script (``python -m forge.codegen.canvas_lint``) to regenerate
the checked-in files inside the forge repo.

The emitter is intentionally **declarative-then-stamp**, not template
substitution. ``_TYPE_RULES`` is a list of :class:`TypeRule` records;
each per-language emitter walks the list and writes the
language-appropriate ``if`` branch. The shape parallels
:mod:`forge.codegen.canvas_props` (the Theme 1B emitter) — banner,
``load`` helper, three emitter functions, and a
``regenerate_packages`` driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Reuse the canvas-props ``SCHEMA_VERSION`` so a single bump captures
# every breaking change across the canvas codegen surface. If lint
# rules ever evolve independently of prop schemas this can grow its own
# version — for v1 a shared tag is the right call.
from forge.codegen.canvas_props import SCHEMA_VERSION


@dataclass(frozen=True)
class TypeRule:
    """One JSON Schema ``type`` branch in the per-property lint loop.

    Each ``TypeRule`` knows how to render itself in TypeScript and Dart.
    The per-language emitter walks ``_TYPE_RULES`` and stamps the
    appropriate ``if``/``else if`` branch. The TS check is expressed
    as a ``typeof``/``Array.isArray``/null guard; the Dart check uses
    ``is!`` and language-native types.

    Fields:
        name:            Canonical rule name (used by tests as a
                         machine-readable identifier).
        json_type:       The JSON Schema ``type`` keyword this rule
                         matches against.
        ts_mismatch:     A TS *expression* that evaluates to ``true``
                         when ``value`` violates the type. Read in
                         scope where ``value`` is the prop value.
        dart_mismatch:   A Dart expression analogue. Read in scope
                         where ``value`` is the prop value.
        message:         Canonical error message **template**. The
                         literal ``{actual}`` placeholder is substituted
                         per language with the right runtime-type
                         expression (``typeof value`` in TS,
                         ``value.runtimeType`` in Dart).
    """

    name: str
    json_type: str
    ts_mismatch: str
    dart_mismatch: str
    message: str


# Canonical type-check rules. Ordering matches the existing hand-written
# files (string → integer → number → boolean → array → object) so the
# generated code reads like the originals and so fingerprint tests stay
# stable across the swap.
_TYPE_RULES: tuple[TypeRule, ...] = (
    TypeRule(
        name="string",
        json_type="string",
        ts_mismatch="typeof value !== 'string'",
        dart_mismatch="value is! String",
        message="expected string, got {actual}",
    ),
    TypeRule(
        name="integer",
        json_type="integer",
        # In TS we additionally guard against non-integer ``number``s
        # (e.g. ``1.5``) — JS has only one numeric type, so a ``typeof
        # value === 'number'`` check is not enough.
        ts_mismatch="typeof value !== 'number' || !Number.isInteger(value)",
        # Dart ``int`` and ``double`` are disjoint subtypes of ``num``,
        # so a single ``is! int`` covers both "is not a number" and
        # "is a non-integer number".
        dart_mismatch="value is! int",
        message="expected integer, got {actual}",
    ),
    TypeRule(
        name="number",
        json_type="number",
        ts_mismatch="typeof value !== 'number'",
        dart_mismatch="value is! num",
        message="expected number, got {actual}",
    ),
    TypeRule(
        name="boolean",
        json_type="boolean",
        ts_mismatch="typeof value !== 'boolean'",
        dart_mismatch="value is! bool",
        message="expected boolean, got {actual}",
    ),
    TypeRule(
        name="array",
        json_type="array",
        ts_mismatch="!Array.isArray(value)",
        dart_mismatch="value is! List",
        message="expected array, got {actual}",
    ),
    TypeRule(
        name="object",
        json_type="object",
        # In TS, ``typeof null === 'object'`` and ``typeof [] ===
        # 'object'`` — must exclude both explicitly.
        ts_mismatch="typeof value !== 'object' || Array.isArray(value) || value === null",
        # Dart ``Map`` does not include ``List`` or ``null`` so a single
        # ``is!`` suffices.
        dart_mismatch="value is! Map",
        message="expected object, got {actual}",
    ),
)


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------


def _banner_lines_ts() -> list[str]:
    """Banner emitted at the top of generated TS lint files."""
    return [
        "// AUTOGENERATED — DO NOT EDIT.",
        "// Source: forge/codegen/canvas_lint.py",
        f"// Schema version: {SCHEMA_VERSION}",
        "// Regenerate via `python -m forge.codegen.canvas_lint`.",
        "//",
        "// Runtime lint for canvas component props.",
        "//",
        "// Dev-mode only: compares backend-supplied props against the component's",
        "// registered JSON Schema and emits `console.warn` on each mismatch so",
        "// prop drift (backend adding a field, frontend not updated) surfaces",
        "// immediately in the browser console instead of silently rendering",
        "// undefined. Production builds short-circuit warnOnLintIssues to a no-op.",
        "",
    ]


def _banner_lines_dart() -> list[str]:
    """Banner emitted at the top of the generated Dart lint file."""
    return [
        "// AUTOGENERATED — DO NOT EDIT.",
        "// Source: forge/codegen/canvas_lint.py",
        f"// Schema version: {SCHEMA_VERSION}",
        "// Regenerate via `python -m forge.codegen.canvas_lint`.",
        "//",
        "// Runtime lint for canvas component props.",
        "//",
        "// Dev-mode (`!kReleaseMode`) only: compares the payload props against",
        "// the component's registered JSON Schema and emits `debugPrint` on each",
        "// mismatch so prop drift surfaces in the Flutter logs instead of",
        "// silently rendering a blank widget.",
        "",
    ]


# ---------------------------------------------------------------------------
# TypeScript emitter
# ---------------------------------------------------------------------------


def _emit_ts_type_branch(rule: TypeRule, *, is_first: bool) -> str:
    """Render one ``if``/``else if`` branch for a TS ``TypeRule``."""
    keyword = "if" if is_first else "} else if"
    msg = rule.message.replace("{actual}", "${typeof value}")
    return (
        f"    {keyword} (ty === '{rule.json_type}' && ({rule.ts_mismatch})) {{\n"
        f"      issues.push({{ field: name, message: `{msg}` }})"
    )


def emit_typescript(rules: tuple[TypeRule, ...] = _TYPE_RULES) -> str:
    """Emit the TypeScript lint module body.

    The same string is written into both ``canvas-vue`` and
    ``canvas-svelte``; the two packages do not need their own variants
    because the lint logic is framework-agnostic (it consumes plain
    JSON Schema and plain JS objects).
    """
    lines: list[str] = list(_banner_lines_ts())
    lines.extend(
        [
            "export interface LintIssue {",
            "  field: string",
            "  message: string",
            "}",
            "",
            "/**",
            " * Validate `props` against a canvas component's declared JSON Schema.",
            " * Returns an empty array when the props are OK.",
            " *",
            " * Intentionally shallow — only top-level property types + required",
            " * fields + additionalProperties + enum are checked. Nested objects",
            " * and arrays pass through without recursion.",
            " */",
            "export function lintProps(",
            "  propsSchema: Record<string, unknown> | undefined,",
            "  props: Record<string, unknown>,",
            "): LintIssue[] {",
            "  if (!propsSchema) return []",
            "  const issues: LintIssue[] = []",
            "  const properties = (propsSchema.properties as Record<string, Record<string, unknown>>) || {}",
            "  const required = (propsSchema.required as string[]) || []",
            "  const additionalOk = propsSchema.additionalProperties === true",
            "",
            "  for (const name of required) {",
            "    if (!(name in props)) {",
            "      issues.push({ field: name, message: 'required prop is missing' })",
            "    }",
            "  }",
            "",
            "  for (const [name, value] of Object.entries(props)) {",
            "    const schema = properties[name]",
            "    if (!schema) {",
            "      if (!additionalOk) {",
            "        issues.push({ field: name, message: 'unknown prop' })",
            "      }",
            "      continue",
            "    }",
            "    const ty = schema.type as string | undefined",
        ]
    )

    # Type branches — chained if / else if, closed by a trailing ``}``.
    if rules:
        for idx, rule in enumerate(rules):
            lines.append(_emit_ts_type_branch(rule, is_first=(idx == 0)))
        lines.append("    }")
    # If no rules were defined, no type-branch chain is emitted (no-op).

    lines.extend(
        [
            "    // Enum check",
            "    const enumValues = schema.enum as unknown[] | undefined",
            "    if (enumValues && !enumValues.includes(value)) {",
            "      issues.push({ field: name, message: `not in enum ${JSON.stringify(enumValues)}` })",
            "    }",
            "  }",
            "",
            "  return issues",
            "}",
            "",
            "/**",
            " * Warn about prop drift via console.warn in dev mode. No-op in prod.",
            " */",
            "export function warnOnLintIssues(componentName: string, issues: LintIssue[]): void {",
            "  if (issues.length === 0) return",
            "  // Vite sets import.meta.env.PROD; fall back to process.env.NODE_ENV so",
            "  // non-Vite builds (Webpack, Rspack, etc.) still get the dev-mode warn.",
            "  const isProd =",
            "    // @ts-ignore — import.meta.env is Vite-specific; guard at runtime.",
            "    (typeof import.meta !== 'undefined' && import.meta.env?.PROD === true) ||",
            "    (typeof process !== 'undefined' && process.env?.NODE_ENV === 'production')",
            "  if (isProd) return",
            "  // eslint-disable-next-line no-console",
            "  console.warn(",
            "    `[forge:canvas] ${componentName}: ${issues.length} prop lint issue(s)`,",
            "    issues,",
            "  )",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dart emitter
# ---------------------------------------------------------------------------


def _emit_dart_type_branch(rule: TypeRule, *, is_first: bool) -> str:
    """Render one ``if``/``else if`` branch for a Dart ``TypeRule``."""
    keyword = "if" if is_first else "} else if"
    msg = rule.message.replace("{actual}", "${value.runtimeType}")
    return (
        f"    {keyword} (ty == '{rule.json_type}' && ({rule.dart_mismatch})) {{\n"
        f"      issues.add(LintIssue(field: entry.key, message: '{msg}'));"
    )


def emit_dart(rules: tuple[TypeRule, ...] = _TYPE_RULES) -> str:
    """Emit the Dart lint library body."""
    lines: list[str] = list(_banner_lines_dart())
    lines.extend(
        [
            "import 'package:flutter/foundation.dart';",
            "",
            "class LintIssue {",
            "  final String field;",
            "  final String message;",
            "",
            "  const LintIssue({required this.field, required this.message});",
            "",
            "  @override",
            "  String toString() => '$field: $message';",
            "}",
            "",
            "List<LintIssue> lintProps(",
            "  Map<String, dynamic>? propsSchema,",
            "  Map<String, dynamic> props,",
            ") {",
            "  if (propsSchema == null) return const [];",
            "",
            "  final issues = <LintIssue>[];",
            "  final properties = (propsSchema['properties'] as Map<String, dynamic>?) ?? const {};",
            "  final required = (propsSchema['required'] as List<dynamic>?)?.cast<String>() ?? const [];",
            "  final additionalOk = propsSchema['additionalProperties'] == true;",
            "",
            "  for (final name in required) {",
            "    if (!props.containsKey(name)) {",
            "      issues.add(LintIssue(field: name, message: 'required prop is missing'));",
            "    }",
            "  }",
            "",
            "  for (final entry in props.entries) {",
            "    final schema = properties[entry.key] as Map<String, dynamic>?;",
            "    if (schema == null) {",
            "      if (!additionalOk) {",
            "        issues.add(LintIssue(field: entry.key, message: 'unknown prop'));",
            "      }",
            "      continue;",
            "    }",
            "    final ty = schema['type'] as String?;",
            "    final value = entry.value;",
        ]
    )

    if rules:
        for idx, rule in enumerate(rules):
            lines.append(_emit_dart_type_branch(rule, is_first=(idx == 0)))
        lines.append("    }")

    lines.extend(
        [
            "    // Enum check",
            "    final enumValues = schema['enum'] as List<dynamic>?;",
            "    if (enumValues != null && !enumValues.contains(value)) {",
            "      issues.add(LintIssue(field: entry.key, message: 'not in enum $enumValues'));",
            "    }",
            "  }",
            "",
            "  return issues;",
            "}",
            "",
            "void warnOnLintIssues(String componentName, List<LintIssue> issues) {",
            "  if (issues.isEmpty || kReleaseMode) return;",
            "  debugPrint('[forge:canvas] $componentName: ${issues.length} prop lint issue(s):');",
            "  for (final issue in issues) {",
            "    debugPrint('  $issue');",
            "  }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Repo-side regeneration
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Return the forge repo root (three levels above this file)."""
    return Path(__file__).resolve().parent.parent.parent


_PACKAGE_TARGETS: tuple[tuple[str, str], ...] = (
    ("typescript", "packages/canvas-vue/src/lint.ts"),
    ("typescript", "packages/canvas-svelte/src/lint.ts"),
    ("dart", "packages/forge-canvas-dart/lib/src/lint.dart"),
)


def regenerate_packages(
    repo_root: Path | None = None,
    rules: tuple[TypeRule, ...] = _TYPE_RULES,
) -> list[Path]:
    """Regenerate the three lint files under ``packages/`` in the forge repo.

    Returns the list of paths written, sorted. Idempotent: writes are
    byte-identical on repeated invocations.
    """
    root = repo_root or _repo_root()
    bodies = {
        "typescript": emit_typescript(rules),
        "dart": emit_dart(rules),
    }
    written: list[Path] = []
    for lang, rel in _PACKAGE_TARGETS:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bodies[lang], encoding="utf-8")
        written.append(target)
    return sorted(written)


def main() -> int:
    """CLI entry point: regenerate every canvas-lint target in the repo."""
    written = regenerate_packages()
    for p in written:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
