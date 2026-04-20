# Upgrading forge

This document lists breaking changes per version and the migration steps for each.

## 0.x → 1.0

forge 1.0 is a clean-break release. The high-level shifts:

1. **Schema-first core** — TypeSpec drives CRUD entities; JSON Schema drives the agentic-UI protocol. Hand-written domain and protocol types are replaced by generated files.
2. **AST-aware injection** — text-marker injection is replaced by LibCST (Python) and ts-morph (TypeScript). Users can now reformat generated code freely.
3. **Three-zone merge** — `forge --update` respects user-owned regions. No more silent overwrites or silent skips.
4. **Ports-and-adapters** — integrations are swappable at runtime. Config change, not regeneration.
5. **Plugin surface** — third parties can ship backends, frontends, fragments, commands, and emitters via `importlib.metadata` entry points.

The overall migration path:

```bash
# 1. Pin your current forge version
forge --version                            # note this

# 2. Re-generate or migrate
forge migrate                              # new 1.0 umbrella command (when available)
#   OR, for a clean break:
forge new --config forge.yaml              # regenerate in a fresh directory
```

## Per-phase breaking changes

This section is populated as each 1.0 alpha ships.

### 1.0.0a1 — Phase 0 foundations (unreleased)

- **CLI entry point** — `forge.cli:main` → `forge.cli.main:main` (same `forge` console script). Code importing `from forge.cli import main` should continue to work via re-export, but code importing private helpers (`_build_parser`, `_Resolver`, etc.) must update to the new paths.
- **`forge.toml`** — new `[forge.provenance]` table. Old projects lacking it will receive a one-time backfill with a warning on the first `forge --update` in 1.0.

### 1.0.0a2 — Phase 1 schema-first (unreleased)

_To be populated when Phase 1 alpha ships._

### 1.0.0a3 — Phase 2 extensibility (unreleased)

_To be populated when Phase 2 alpha ships._

### 1.0.0a4 — Phase 3 agentic-UI upgrade (unreleased)

_To be populated when Phase 3 alpha ships._

### 1.0.0b1 — Phase 4 polish (unreleased)

_To be populated when Phase 4 beta ships._

---

## Codemods and tooling

When a mechanical migration is possible, forge ships a `forge migrate-<x>` codemod:

| Codemod | Availability | What it does |
|---|---|---|
| `forge migrate` | Post-1.0.0a1 | Umbrella — runs all applicable migrations for a project |
| `forge migrate-entities` | Post-1.0.0a2 | Translate hand-written domain/*.py, prisma/schema.prisma, models.rs to a generated `domain/*.tsp` |
| `forge migrate-ui-protocol` | Post-1.0.0a2 | Delete hand-written `types.ts` / `chat.types.ts` / `agent_state.dart`; re-run generator |
| `forge migrate-adapters` | Post-1.0.0a3 | Restructure `src/app/rag/` into `src/app/ports/` + `src/app/adapters/vector_store/` |

Each codemod is idempotent and safe to re-run.

## Rollback

If an upgrade fails, every alpha/beta retains an installable identity on PyPI. Rollback is:

```bash
uv pip install "forge==0.X.Y"    # your last working version
```

and discard the `1.0-dev` workspace. The `0.x-final` tag is the stable reference.
