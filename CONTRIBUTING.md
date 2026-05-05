# Contributing to forge

Thanks for your interest. Forge is a small CLI; the codebase is intentionally compact and the bar for changes is keeping it that way.

## Setup

```bash
git clone <repo>
cd forge
uv sync --all-extras --dev
uv run pre-commit install
```

## Local CI parity

Before pushing, run:

```bash
make check
```

That target runs `ruff check` + `ruff format --check` + `ty check` +
`pytest` — the same gates push-CI's `lint`, `typecheck-forge`, and
`test` jobs enforce. The matrix-verify lanes (which need Node + Rust
toolchains) run only in CI; for a local generator-only sweep use
`make validate-matrix`.

`uv run pre-commit install` (run once during **Setup**) catches ruff
and ty drift on every commit, so `make check` rarely surprises you.

## Workflow

```bash
make check       # ruff (check + format --check) + ty + unit tests (fast, ~10s)
make lint        # ruff check
make format      # ruff format (writes)
make format-check # ruff format --check (read-only — same as CI)
make typecheck   # ty check
make test        # pytest (excludes -m e2e)
make e2e         # full e2e suite (slow — needs uv, npm, cargo, git)
```

CI runs `make check` on Linux + Windows for Python 3.11/3.12/3.13. The `e2e` workflow runs nightly and on PRs that touch templates or the generator.

## Adding a new feature

- **New backend language**: see [docs/adding-a-backend.md](docs/adding-a-backend.md). The `BACKEND_REGISTRY` is the single source of truth.
- **New CLI flag**: add to `_parse_args` in `forge/cli.py` and read via `_get(args, "flag", cfg, "block", "key", default=...)` in `_build_config`.
- **Template change**: bump nothing — versioning is by git commit (recorded in `forge.toml` of generated projects via the `_commit:` Copier directive). Add an e2e case if behaviour changes.
- **New error path**: raise `GeneratorError` from `forge.errors`; `cli.main()` already routes it to JSON envelope or stderr+exit(2).

## Architectural decisions vs forge RFCs

Two separate doc trees, on purpose — they cover different scopes:

- **`docs/architecture-decisions/ADR-NNN-*.md`** — decisions about the
  **shape of projects forge generates**. Audience: someone reading a
  forge-generated codebase who wants to know why it's structured that
  way. Examples: ADR-001 (pragmatic hexagonal layering), ADR-002 (ports
  + adapters for swappable integrations).
- **`docs/rfcs/RFC-NNN-*.md`** — decisions about **forge itself**:
  versioning, release process, plugin contract, error contract,
  config-loading semantics. Audience: forge contributors and plugin
  authors. The folder's `README.md` documents when to write one and
  the template shape.

When in doubt: if the change affects what `forge new` *emits*, it's an
ADR. If it affects how the `forge` CLI / SDK *behaves*, it's an RFC.

## Code style

- Type hints required on all public functions and module-level callables; `ty check forge/` must pass.
- Lint rules: `ruff` with `select = E,F,I,UP,B,SIM`, line length 100, exclude `forge/templates/`.
- No new dependencies without a clear motivation; keep the install footprint small.
- Tests live in `tests/`; e2e cases live in `tests/e2e/` and are marked `@pytest.mark.e2e`.

## Commit & PR conventions

- Subject ≤ 50 chars, imperative mood (`add Go backend support`, `fix git init crash on Windows`).
- One logical change per PR; keep refactors and feature additions separate.
- PR description: motivation + a one-line "how to verify" (typically a `make` target or `uv run forge ...` command).
- The CHANGELOG is updated on release, not per-PR.

## Reporting issues

Include:
- `forge --help` output (confirms version)
- The exact `forge ...` command that triggered the issue
- For generation bugs: the contents of `forge.toml` from the generated project
- For template bugs: the rendered file's location relative to the project root
