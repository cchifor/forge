# Implementation review — feat/domain-emitters-hardening — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 10 findings; 9 ACCEPT, 1 PUSHBACK addressed) -->

## Codex verdict

**ACCEPT with one PUSHBACK** — change `UnknownEnumReferenceError` base class
from `ValueError` to `ForgeError` (via the existing `GeneratorError` alias
the module already imports for "Unknown field type" raises).

## Findings + responses

### 1. Enum validation semantics (ACCEPT)
`known_enums=None` opt-in correctly preserves back-compat. Production
caller (Pillar C.2 pipeline wiring) passes a real set; legacy fixtures /
callers without a registry skip validation. Tests cover both paths.

### 2. `UnknownEnumReferenceError` base class (PUSHBACK → ADDRESSED)
**Codex's verification:** grepped `forge/codegen/pipeline.py` + related
modules. **No `except ValueError` handlers exist for emitter validation.**
The agent's justification was unsupported. The existing emitter code uses
`GeneratorError` (aliased to `ForgeError`) for spec programming errors
("Unknown field type" raises at multiple sites). Enum xref failures are
analogous and belong in the same error family.

**Response:** changed base class to `GeneratorError`. Docstring updated to
explain the rationale: spec-validation failures live in the same family as
the rest of the emitters' programming-error surface; Pillar C.2 can catch
`ForgeError` for a consistent user-facing envelope without depending on a
stdlib-exception contract.

### 3. `emit_alembic_migration` fidelity (ACCEPT)
Codex verified end-to-end against `0001_initial.py` reference:
- UUID PK with `gen_random_uuid()` default ✓
- `sa.String(64)` for enums (matches `native_enum=False` ORM side) ✓
- `created_at`/`updated_at` `server_default=sa.func.now()` ✓
- Index naming strips trailing `_id` ✓
- `downgrade()` correctly inverse of `upgrade()` ✓
- Test coverage robust (13 tests in `TestEmitAlembicMigration`)

### 4. `emit_sqlalchemy_model` correctness (ACCEPT)
SQLAlchemy 2.0 idioms verified:
- `Mapped[T]` + `mapped_column()` typed style ✓
- `__tablename__` + `__table_args__` with `Index(...)` ✓
- UUID PK `default=uuid.uuid4` client-side ✓
- Enum fields use `Enum(..., create_constraint=False, native_enum=False)` —
  app owns value list ✓
- Type mapping (`_sqla_py_type`, `_sqla_type`) covers all spec types ✓

### 5. Pydantic/SQLA isolation (ACCEPT)
Zero shared emit logic. Tests assert ORM body contains no `pydantic` and
Pydantic body contains no `sqlalchemy` / `Mapped`.

### 6. Test coverage (ACCEPT)
33 tests across 4 classes — all key edge cases covered.

### 7. Commit message (ACCEPT)
50 chars exact, imperative, scope ✓.

### 8. CHANGELOG entries (ACCEPT)
`### Added` + `### Changed` under `[Unreleased]`. Honest + accurate.

### 9. Pillar C.2 readiness (ACCEPT)
Function signatures stable: `*, known_enums: Iterable[str] | None = None`
accepts sets/lists/tuples/generators. C.2 pipeline can pass whatever it
builds from `_shared/domain/enums/*.yaml`.

### 10. Worktree artifacts (CLEAN)
No `.claude/worktrees/...` in diff. Clean.

## Convergence

10 findings — 9 ACCEPT, 1 PUSHBACK addressed via base-class change. No
round 2 dispatched — single mechanical fix; codex's analysis was correct
on first pass.

## Diff stat (final)

```
 CHANGELOG.md                  |  41 +++++
 forge/domain/emitters.py      | 418 +++++++++++++++++++++++++++++++++++++++++-
 tests/test_domain_emitters.py | 258 ++++++++++++++++++++++++++
 3 files changed, 707 insertions(+), 10 deletions(-)
```

Plus this impl-review file.
