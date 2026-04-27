# RFC-010 — Schema-driven domain modelling as forge's differentiator

| Field | Value |
| --- | --- |
| Status | Proposed |
| Author | Epic 5 (architectural-improvements-2026-04) |
| Epic | 1.2.0 (target) |
| Supersedes | — |
| Replaces | — |

## Summary

Promote **schema-driven domain modelling** — defining entities once in
TypeSpec or YAML and generating SQLAlchemy + Pydantic + Prisma + Zod +
sqlx + Dart DTOs from the same source of truth — from a partially-wired
internal capability to forge's headline differentiator. This RFC
proposes the user-facing DSL, the generator pipeline shape, the
``forge --new-entity`` UX, and the migration path for the hard-coded
``Item`` example entity that ships in every base template today.

## Motivation

Forge today registers 38 user-facing options across 54 fragments, but
the **domain model** of a generated project — the per-project entities
that drive CRUD endpoints, ORM models, OpenAPI specs, frontend forms —
is hard-coded as an ``Item`` example in each backend template. 90% of
users delete that example first thing and write their own, **losing**
the test scaffolding, ORM-OpenAPI sync, and frontend form generation
along the way.

Internally, the codegen pipeline (``forge/codegen/pipeline.py``) and
domain emitters (``forge/domain/emitters.py``, ``forge/domain/typespec.py``)
already exist and emit the right shapes. They drive the **shared
enums** and **UI protocol types** today; they do not yet drive
**user-defined entities**. The bridge from "user defines a domain
schema" → "all six target shapes get emitted in sync" is the missing
piece.

This is the differentiation answer to *"what makes forge different
from create-react-app / cookiecutter / a curl-able shell script?"*
The polyglot multi-backend story already differentiates forge at
generation time; schema-driven domain modelling differentiates at
**every-day-after-generation** — the user lives inside the domain
model long after the scaffold is forgotten.

## Non-goals

* **Replace ORM mapping libraries.** SQLAlchemy / Prisma / sqlx stay
  the runtime libraries. forge generates their declarations from
  schema; it does not rebuild what they do.
* **Become a database migration tool.** Alembic / Prisma migrate / sqlx
  migrate stay the migration runtimes; forge can scaffold the *first*
  migration from a schema diff but does not own the migration
  lifecycle.
* **Frontend state-management opinions.** forge generates DTOs +
  schema validation + form scaffolds; it doesn't pick TanStack Query
  vs SWR vs Pinia.

## Proposal

### TypeSpec as the canonical DSL, YAML as the on-ramp

TypeSpec is the **canonical** entity definition language going
forward. It compiles to OpenAPI 3.1, which forge already emits
through ``forge/domain/typespec.py``. Authors write::

```typespec
@route("/workflows")
namespace Workflows;

model Workflow {
  @key id: int32;
  name: string;
  status: "active" | "paused" | "archived";
  @createdOn createdAt: utcDateTime;
  ownerId: int32;
}
```

…and ``forge new-entity`` emits SQLAlchemy + Pydantic + (where the
target backend ships) Prisma + Zod + sqlx + Dart DTOs against that
single source. TypeSpec is the canonical because:

1. It already has industry-standard OpenAPI 3.1 emit, so the tooling
   ecosystem (Stainless, Speakeasy, OpenAPI Generator) interoperates
   automatically.
2. It expresses cross-cutting concerns (auth, pagination, versioning)
   without per-target boilerplate.
3. The Microsoft-stewarded spec gives us a stable target the project
   can rely on across forge versions.

YAML stays the **on-ramp** for users not yet ready to install the
``tsp`` CLI. The bridge in ``forge/domain/emitters.py`` already
handles a subset of the YAML shape; this RFC formalises the schema and
caps the YAML feature set at "what TypeSpec express in 1.0" so YAML →
TypeSpec migration is mechanical.

### Generation pipeline

``forge new-entity Workflow --field name:str --field status:enum:active,paused,archived``
becomes the headline UX. The pipeline:

1. CLI assembles a TypeSpec model fragment from the flags (or accepts
   a ``--from-tsp path/to/file.tsp`` for hand-authored definitions).
2. The TypeSpec compiler emits OpenAPI 3.1.
3. Per-backend emitters consume OpenAPI:
   * Python: SQLAlchemy ORM model + alembic migration + Pydantic v2
     DTO + FastAPI route stub.
   * Node: Prisma schema entry + ``prisma migrate dev`` invocation +
     Zod DTO + Fastify route stub.
   * Rust: sqlx migration + struct + serde derive + axum route stub.
4. Per-frontend emitters:
   * Vue/Svelte: TypeScript type from the shared OpenAPI; DataTable
     + DynamicForm scaffolds keyed by the entity's field metadata.
   * Flutter: Dart DTO from the same OpenAPI via openapi-generator.
5. Codegen pipeline records every emit in the provenance manifest
   under ``origin="domain-emitter"`` so ``forge --update`` can
   regenerate when the schema changes without losing user edits.

### `_examples/items_entity` strip

The hardcoded ``Item`` CRUD that ships in every backend template
becomes an opt-in fragment ``_examples/items_entity``, enabled by
default. Users can ``--set platform.example_entity=false`` to start
from a clean entity surface. Existing forge users adopting Epic 5
keep the example by default; new users picking ``--minimal`` get the
clean state.

### `--update` semantics for entities

A user editing the generated SQLAlchemy model directly is the
expected workflow — emitters mark the *body* of generated classes as
``user`` zone (preserve on update) while keeping ``__tablename__``,
imports, and the field-list block in the ``merge`` zone (three-way
decide). The same zone discipline already applies to fragment-emitted
files; this RFC extends it to domain-emitted files.

The provenance manifest's ``[forge.merge_blocks]`` table grows to
cover entity-emitter blocks; no new format work required.

## Migration path

### Phase 1 (1.2.0-alpha) — TypeSpec hardening

* Polish the ``forge/domain/typespec.py`` bridge so the compiler runs
  cleanly on Python/Node/Rust toolchains via ``npx tsp compile``.
* Ship 3-5 TypeSpec example schemas under ``examples/typespec/`` —
  ``Workflow``, ``Tenant``, ``Webhook``, ``Document``.
* ``forge new-entity --from-tsp <path>`` works end-to-end on a
  Python+Vue project.

### Phase 2 (1.2.0-beta) — full target coverage

* ``forge new-entity`` works on every backend × frontend combination
  in the matrix.
* ``_examples/items_entity`` fragment lands; the items hardcode
  comes out of the base templates.
* ``forge --update`` regenerates entity outputs cleanly under three-
  way merge.

### Phase 3 (1.2.0 GA) — UX polish

* ``forge new-entity`` flag-based authoring (no need to write
  TypeSpec for the simple case) emits a ``.tsp`` file alongside
  the generated code; the ``.tsp`` is the source of truth from
  that point on.
* ``forge entity diff`` shows the schema-vs-emitted-code drift
  (catches manual edits to fields that should round-trip through
  the schema).
* Documentation: ``docs/domain-modelling.md`` walkthrough; an
  ``examples/typespec-saas-skeleton/`` reference project.

## Open questions

1. **Migration safety.** Schema changes can drop columns. Should
   ``forge new-entity`` refuse destructive diffs by default and
   require ``--allow-data-loss``? Likely yes; matches Prisma /
   alembic behaviour.

2. **Per-target opt-out.** Some users want the schema to drive
   Python-only and hand-roll the Rust side. Should
   ``Fragment.parity_tier``-style metadata exist for entities?
   Probably overkill — the emitter set is configurable per-project
   via options (``domain.emitters=[python,vue]``).

3. **Plugin emitters.** Today plugins can register fragment-level
   emitters via ``ForgeAPI.add_emitter`` (provisional surface). RFC-
   010 should bump this to stable + extend the contract to cover
   domain emitters. Tracking under Epic 3.

4. **Frontend route generation.** Should generated routes include
   auth-wired guards by default? Probably keyed by the same
   ``frontend.include_auth`` option that already exists.

## Effort estimate

* Phase 1: 2 weeks (TypeSpec bridge polish + examples + new-entity
  bootstrap).
* Phase 2: 3-4 weeks (per-target full coverage, items strip,
  ``--update`` integration).
* Phase 3: 2-3 weeks (UX polish, docs, reference project).

Total: 7-9 weeks of focused engineering. This is the longest single
epic in the architectural-improvements plan; that cost is what makes
schema-driven domain modelling the strategic differentiator rather
than a sprint-sized feature.

## References

* RFC-006 — cross-backend fragment contract (the parity model this
  RFC inherits for the entity-emitter target set).
* ADR-002 — ports and adapters (the architectural shape entity
  emitters target).
* TypeSpec ([microsoft.github.io/typespec](https://microsoft.github.io/typespec/)).
* Existing implementation hooks: ``forge/domain/emitters.py``,
  ``forge/domain/typespec.py``, ``forge/codegen/pipeline.py``,
  ``forge/cli/commands/new_entity.py``.
