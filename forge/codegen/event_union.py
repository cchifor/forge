"""Generate an exhaustive AG-UI event discriminated union (Theme 2B).

The seven schemas under ``forge/templates/_shared/ui-protocol/*.schema.json``
describe the distinct payload shapes the AG-UI surface ships between the
agent backend and the frontend canvas. The shapes are heterogeneous —
``AgUiPayload`` and ``McpExtPayload`` carry an ``engine`` string-const
field; ``WorkspaceActivity`` carries an ``engine`` enum; the remaining
four (``AgentState``, ``HitlResponse``, ``ToolCallInfo``,
``UserPromptPayload``) carry no shared discriminator at all.

The 1B codegen emits each schema as a standalone type
(``forge.codegen.canvas_props`` / ``forge.codegen.ui_protocol``). Theme
2B layers a **synthesised** ``kind`` discriminator on top so a single
``AgUiEvent`` union covers all seven variants, with exhaustive
``never``-checking at consumer call-sites.

Targets:

    * ``packages/canvas-{vue,svelte}/src/generated/events.ts`` —
      TypeScript discriminated union over intersection types, plus an
      ``assertUnreachable(_: never): never`` helper and a
      ``getEventKind`` runtime discriminator.
    * ``packages/forge-canvas-dart/lib/src/generated/events.dart`` —
      Dart 3 ``sealed class AgUiEvent`` with one ``final class`` per
      variant. Dart's exhaustiveness checking on sealed-class switches
      is the language-native equivalent of TS's ``never``.
    * ``services/<name>/src/app/domain/canvas_events.py`` — Pydantic v2
      ``Annotated[Union[...], Field(discriminator="kind")]`` per
      Python backend.

The synthesised ``kind`` slugs are derived from each schema's title via
``_pascal_to_kebab`` (``AgUiPayload`` → ``"ag-ui-payload"``) so the slug
is stable, readable, and adding a new schema produces a new slug
automatically. No manual mapping table — drift between schema set and
emitted union is impossible by construction.

Two helpers ship alongside the union:

    * ``assertUnreachable`` (TS) — call from the ``default`` branch of a
      switch over ``AgUiEvent.kind``. Adding a new variant breaks the
      compile until every consumer is updated.
    * ``getEventKind`` (TS) / ``AgUiEvent.kind`` getter (Dart) —
      runtime discriminator extraction. Pydantic gets this for free
      from its ``Field(discriminator=)`` machinery.
"""

from __future__ import annotations

import re
from pathlib import Path

from forge.codegen.ui_protocol import (
    DEFAULT_SCHEMA_ROOT as UI_PROTOCOL_ROOT,
)
from forge.codegen.ui_protocol import (
    Schema,
    _dart_for_schema,
    _ts_for_schema,
    load_all,
)

# Bump when the union shape changes incompatibly (kind slugs renamed,
# helper signatures changed, etc.). Mirrors canvas_props.SCHEMA_VERSION.
SCHEMA_VERSION = 1

# Centralized `@ag-ui/client` + `@ag-ui/core` version pin. Lives next to
# the event-union codegen because the union is the protocol contract
# with the AG-UI runtime, so any time the version moves the union may
# need a re-emit. Every consumer reads from here:
#
#   * Vue + Svelte frontend templates (``package.json.jinja``) consume
#     it via the Copier context (``forge/variable_mapper.py`` exposes
#     ``ag_ui_client_version`` / ``ag_ui_core_version`` to Jinja).
#   * In-tree canvas packages (``packages/canvas-{vue,svelte}/package.json``)
#     pin to the same value; ``tests/test_ag_ui_pin_consistency.py``
#     fails CI on drift.
#
# Bump procedure: change the two constants below, run the consistency
# test, manually update the 2 in-tree canvas-package ``package.json``
# files to match. The test will not let CI go green if the four
# locations disagree.
AG_UI_CLIENT_VERSION = "0.0.56"
AG_UI_CORE_VERSION = "0.0.56"


# -- Slug derivation ---------------------------------------------------------


def _pascal_to_kebab(title: str) -> str:
    """Convert ``PascalCase`` to ``kebab-case``.

    Examples:
        AgUiPayload    -> ag-ui-payload
        McpExtPayload  -> mcp-ext-payload
        HitlResponse   -> hitl-response
        UserPromptPayload -> user-prompt-payload

    Treats acronym runs (consecutive uppercase) as a single word: this
    is the canonical kebab-case rule (``HTTPServer`` → ``http-server``,
    not ``h-t-t-p-server``) and matches how AG-UI's wire protocol slugs
    its existing fields.
    """
    # Split before each uppercase letter that's preceded by a lowercase
    # letter or digit, OR before an uppercase letter that's followed by
    # a lowercase letter (acronym boundary).
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", title)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    return s.lower()


def _kind_for(schema: Schema) -> str:
    """The synthesised ``kind`` slug for ``schema``."""
    return _pascal_to_kebab(schema.title)


def _kinds_list(schemas: list[Schema]) -> list[tuple[str, str]]:
    """Return ``[(title, kind), ...]`` in schema-load order."""
    return [(s.title, _kind_for(s)) for s in schemas]


# -- TypeScript --------------------------------------------------------------


def _banner_ts() -> list[str]:
    return [
        "// AUTOGENERATED — DO NOT EDIT.",
        "// Source: forge/templates/_shared/ui-protocol/*.schema.json",
        f"// Schema version: {SCHEMA_VERSION}",
        "// Regenerate via `python -m forge.codegen.event_union`.",
        "",
    ]


def emit_typescript(schemas: list[Schema]) -> str:
    """Emit the TS discriminated union module.

    The module is self-contained: it inlines every variant interface
    (re-using :func:`forge.codegen.ui_protocol._ts_for_schema`) and
    then layers a synthesised ``kind`` discriminator on top. Self-
    containment matters because the canvas packages don't otherwise
    carry ui-protocol payload types — those types are template-internal
    — so importing the variants from a sibling generated file would
    require shipping an extra layer.

    For each schema title ``T`` we emit:

        export interface T { ... }                   // inlined 1B body
        export type TWithKind = { kind: "<kind>"; payload: T };

    and assemble the union:

        export type AgUiEvent = TWithKind | UWithKind | ...;
        export type AgUiEventKind = "<kind>" | "<kind>" | ...;

    The wire shape (``{kind, payload}`` envelope) matches what the
    Pydantic discriminated-union backend emits — Pydantic v2's
    ``Field(discriminator="kind")`` machinery wraps each variant in a
    dedicated model with ``kind`` + ``payload`` fields, so a generated
    service serializes events in exactly that shape. Mirroring it in
    TS keeps the type contract honest: a value typed ``AgUiEvent`` is
    byte-compatible with the wire payload Pydantic produces and the
    Dart ``AgUiEvent.parse`` factory consumes.

    Pre-Initiative-#4 (Theme 2B) the TS union flattened payload fields
    next to ``kind`` via ``T & {kind: ...}``. That shape disagreed with
    Pydantic and would have failed at runtime against the actual wire;
    Initiative #4 unifies the three runtimes on the wrapped envelope.
    """
    kinds = _kinds_list(schemas)

    lines: list[str] = _banner_ts()

    # Inline every variant interface — keep the file self-contained.
    lines.append("// Variant payload interfaces — inlined from the ui-protocol schemas:")
    for schema in schemas:
        lines.append(_ts_for_schema(schema))
        lines.append("")

    lines.append("// Synthesised `kind` discriminator: each schema's PascalCase title kebab-cased.")
    lines.append("// Wire shape mirrors Pydantic's discriminated-union envelope:")
    lines.append("//   { kind: '<slug>', payload: <variant> }")
    lines.append("// Variant-with-kind aliases — the envelope wrapping each payload:")
    for title, kind in kinds:
        lines.append(f'export type {title}WithKind = {{ kind: "{kind}"; payload: {title} }};')
    lines.append("")

    lines.append("/** The exhaustive AG-UI event union. */")
    union_rhs = "\n  | ".join(f"{title}WithKind" for title, _ in kinds)
    lines.append(f"export type AgUiEvent =\n  | {union_rhs};")
    lines.append("")

    kind_union = " | ".join(f'"{kind}"' for _, kind in kinds)
    lines.append(f"export type AgUiEventKind = {kind_union};")
    lines.append("")

    lines.append("/** Runtime discriminator extraction — mirrors the type-level `kind`. */")
    lines.append("export function getEventKind(event: AgUiEvent): AgUiEventKind {")
    lines.append("  return event.kind;")
    lines.append("}")
    lines.append("")

    lines.append("/**")
    lines.append(" * Exhaustiveness guard for switch/if-chains over `AgUiEvent.kind`.")
    lines.append(" *")
    lines.append(" * Call from the `default` branch (or after the chain). Adding a new")
    lines.append(" * variant turns the call into a compile error in every consumer that")
    lines.append(" * forgot to handle it.")
    lines.append(" */")
    lines.append("export function assertUnreachable(_: never): never {")
    lines.append(
        '  throw new Error("Non-exhaustive AG-UI event union — '
        'a new variant was added without handling");'
    )
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


# -- Dart --------------------------------------------------------------------


def _banner_dart() -> list[str]:
    return _banner_ts()


def emit_dart(schemas: list[Schema]) -> str:
    """Emit the Dart sealed-class hierarchy.

    Dart 3 sealed classes give exhaustive switches for free: the
    analyzer flags any switch over a ``sealed`` type that doesn't
    cover every subclass. That's the Dart equivalent of TS's
    ``assertUnreachable`` — no runtime helper needed.

    The file is self-contained: every payload class is inlined
    (reusing :func:`forge.codegen.ui_protocol._dart_for_schema`) and
    then a sealed-class hierarchy wraps them with a ``kind`` getter.

    A static :meth:`AgUiEvent.parse` factory is also emitted so the
    repo's ``AgUiClient`` (see :file:`packages/forge-canvas-core-dart/lib/src/ag_ui_client.dart`,
    re-exported from ``forge_canvas`` per Pillar B Phase 2B) can be
    wired up without any per-app glue:

        AgUiClient<AgUiEvent>(dio: dio, parser: AgUiEvent.parse, ...)

    ``parse`` switches on the ``kind`` slug, pulls ``json['payload']``,
    delegates to the matching payload's ``.fromJson`` constructor, and
    wraps the result in the sealed subclass. Returns ``null`` when
    ``kind`` is missing or unknown, or when ``payload`` is missing /
    not an object — the caller's ``onParseError`` decides whether to
    surface a synthetic event or drop the frame.

    The wire shape — ``{kind: '<slug>', payload: {...}}`` — mirrors
    the wrapped envelope Pydantic's discriminated-union machinery
    emits on the backend. The TS union in
    :func:`emit_typescript` declares the same envelope. Aligning all
    three runtimes on the wrapped shape is the load-bearing fix of
    Initiative #4: pre-Initiative-#4 the Dart parser called
    ``Title.fromJson(json)`` on the outer envelope, which would have
    failed at runtime against any Pydantic-emitted frame.
    """
    kinds = _kinds_list(schemas)

    lines: list[str] = _banner_dart()
    lines.append("// Variant payload classes — inlined from the ui-protocol schemas:")
    for schema in schemas:
        lines.append(_dart_for_schema(schema))
        lines.append("")

    lines.append("/// Exhaustive AG-UI event union.")
    lines.append("///")
    lines.append("/// Switching over an `AgUiEvent` with Dart 3 sealed-class semantics")
    lines.append("/// makes the analyzer fail any switch that doesn't cover every")
    lines.append("/// subclass — the language-native equivalent of TypeScript's")
    lines.append("/// `assertUnreachable` pattern.")
    lines.append("sealed class AgUiEvent {")
    lines.append("  const AgUiEvent();")
    lines.append("")
    lines.append("  /// The kebab-case kind slug for this variant.")
    lines.append("  String get kind;")
    lines.append("")
    # Factory: kind -> variant. Returns null for missing/unknown kind so
    # AgUiClient<AgUiEvent>(parser: AgUiEvent.parse) wires up directly
    # without per-app glue. Wire shape mirrors Pydantic's wrapped
    # envelope: { kind: '<slug>', payload: {...} } — the discriminator
    # picks the variant, the payload sub-map carries the typed fields.
    lines.append("  /// Parse a raw JSON frame into the matching sealed variant.")
    lines.append("  ///")
    lines.append("  /// Reads the canonical `kind` discriminator, pulls the nested")
    lines.append("  /// `payload` map, and dispatches to the matching payload's")
    lines.append("  /// `fromJson`. Returns `null` when the frame has no `kind`")
    lines.append("  /// field, carries an unknown slug, or is missing the")
    lines.append("  /// `payload` object — the caller's `onParseError` then")
    lines.append("  /// decides whether to surface a synthetic event or drop the")
    lines.append("  /// frame.")
    lines.append("  ///")
    lines.append("  /// Wire shape (mirrors the Pydantic discriminated-union")
    lines.append("  /// envelope on the backend):")
    lines.append("  ///")
    lines.append('  ///     { "kind": "<slug>", "payload": { ...variant fields... } }')
    lines.append("  ///")
    lines.append("  /// Wired into the shipped `AgUiClient` via")
    lines.append("  /// `AgUiClient<AgUiEvent>(parser: AgUiEvent.parse, ...)`.")
    lines.append("  static AgUiEvent? parse(Map<String, dynamic> json) {")
    lines.append("    final kind = json['kind'];")
    lines.append("    if (kind is! String) return null;")
    lines.append("    final rawPayload = json['payload'];")
    lines.append("    if (rawPayload is! Map) return null;")
    lines.append("    final payload = Map<String, dynamic>.from(rawPayload);")
    lines.append("    switch (kind) {")
    for title, kind in kinds:
        case_name = f"{title}Event"
        lines.append(f"      case '{kind}':")
        lines.append(f"        return {case_name}({title}.fromJson(payload));")
    lines.append("      default:")
    lines.append("        return null;")
    lines.append("    }")
    lines.append("  }")
    lines.append("}")
    lines.append("")

    for title, kind in kinds:
        case_name = f"{title}Event"
        lines.append(f"/// `{kind}` variant of [AgUiEvent], wrapping a [{title}] payload.")
        lines.append(f"final class {case_name} extends AgUiEvent {{")
        lines.append(f"  const {case_name}(this.payload);")
        lines.append(f"  final {title} payload;")
        lines.append("  @override")
        lines.append(f"  String get kind => '{kind}';")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


# -- Pydantic ----------------------------------------------------------------


def _banner_pydantic() -> list[str]:
    return [
        '"""AUTOGENERATED — DO NOT EDIT.',
        "",
        "Source: forge/templates/_shared/ui-protocol/*.schema.json",
        f"Schema version: {SCHEMA_VERSION}",
        "Regenerate via ``python -m forge.codegen.event_union`` (forge repo) or",
        "by re-running the per-project codegen pipeline.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Annotated, Literal, Union",
        "",
        "from pydantic import BaseModel, Field, TypeAdapter",
        "",
        "from .ui_protocol import (",
    ]


def emit_pydantic(schemas: list[Schema]) -> str:
    """Emit a Pydantic v2 discriminated-union module.

    Each variant becomes a tiny ``BaseModel`` wrapper that re-exports
    the underlying payload class with an explicit ``kind: Literal[...]``
    field. The outer union uses ``Annotated[Union[...], Field(discriminator="kind")]``
    — Pydantic v2's native discriminated-union machinery.

    A ``TypeAdapter`` is exposed so backend code can validate raw
    dict-shaped events against the union with a single call.
    """
    kinds = _kinds_list(schemas)

    lines: list[str] = _banner_pydantic()
    # Re-import the variant payload classes from the per-project
    # ``ui_protocol.py`` (the 1B Pydantic output) — relative import so
    # the file works under ``app.domain.canvas_events``.
    for i, (title, _) in enumerate(kinds):
        suffix = "," if i < len(kinds) - 1 else ","
        lines.append(f"    {title}{suffix}")
    lines.append(")")
    lines.append("")

    # Emit a kind-bearing wrapper for each variant.
    for title, kind in kinds:
        wrapper = f"{title}Event"
        lines.append(f"class {wrapper}(BaseModel):")
        lines.append(f'    """`{kind}` variant of :data:`AgUiEvent` — wraps a :class:`{title}`."""')
        lines.append("")
        lines.append(f'    kind: Literal["{kind}"] = "{kind}"')
        lines.append(f"    payload: {title}")
        lines.append("")

    # Outer discriminated union. Emit one variant per line so ruff E501
    # (line-too-long) doesn't trip when the variant count grows — a flat
    # single-line ``Union[A, B, C, ...]`` blew past the generated
    # service's 100-char limit once the AG-UI schema set reached ~7
    # variants. Per-line is also the convention `ruff format` produces
    # when it splits a Union, so the auto-fix step finds nothing to do.
    lines.append("AgUiEvent = Annotated[")
    lines.append("    Union[")
    for title, _ in kinds:
        lines.append(f"        {title}Event,")
    lines.append("    ],")
    lines.append('    Field(discriminator="kind"),')
    lines.append("]")
    lines.append('"""Exhaustive AG-UI event union, discriminated by ``kind``."""')
    lines.append("")
    lines.append("AgUiEventAdapter: TypeAdapter[AgUiEvent] = TypeAdapter(AgUiEvent)")
    lines.append('"""Validate a raw dict against :data:`AgUiEvent`."""')
    lines.append("")

    return "\n".join(lines)


# -- Repo-side regeneration --------------------------------------------------


DEFAULT_SCHEMA_ROOT = UI_PROTOCOL_ROOT


def load_event_schemas(root: Path | None = None) -> list[Schema]:
    """Load every ``ui-protocol`` schema in title order."""
    return load_all(root or DEFAULT_SCHEMA_ROOT)


def _repo_root() -> Path:
    """Return the forge repo root, three levels above this file."""
    return Path(__file__).resolve().parent.parent.parent


_PACKAGE_TARGETS: tuple[tuple[str, str], ...] = (
    ("typescript", "packages/canvas-vue/src/generated/events.ts"),
    ("typescript", "packages/canvas-svelte/src/generated/events.ts"),
    ("dart", "packages/forge-canvas-dart/lib/src/generated/events.dart"),
)


def regenerate_packages(repo_root: Path | None = None) -> list[Path]:
    """Regenerate event-union files under ``packages/`` in the forge repo.

    Returns the list of paths written, sorted. Idempotent: writes are
    byte-identical on repeated invocations.
    """
    root = repo_root or _repo_root()
    schemas = load_event_schemas()
    bodies = {
        "typescript": emit_typescript(schemas),
        "dart": emit_dart(schemas),
    }
    written: list[Path] = []
    for lang, rel in _PACKAGE_TARGETS:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(bodies[lang], encoding="utf-8")
        written.append(target)
    return sorted(written)


def main() -> int:
    """CLI entry point: regenerate every event-union target in the repo."""
    written = regenerate_packages()
    for p in written:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
