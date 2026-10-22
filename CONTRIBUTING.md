# Contributing to forge

Thanks for your interest. Forge is a small CLI; the codebase is intentionally compact and the bar for changes is keeping it that way.

## Setup

You do not need write access to contribute. Anyone with a GitHub account can
open a pull request, but only collaborators can push branches to
`cchifor/forge`. A `git push` from a plain clone of this repository fails with
`Write access to repository not granted` (HTTP 403). Fork the repository and
push your branches to the fork:

```bash
gh repo fork cchifor/forge --clone   # or fork in the web UI and clone your fork
cd forge
uv sync --all-extras --dev
uv run pre-commit install
```

`gh repo fork --clone` adds this repository as the `upstream` remote. If you
already cloned `cchifor/forge`, run `gh repo fork --remote` inside that clone.
It renames the `origin` remote to `upstream` and adds your fork as `origin`.

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

CI runs generator checks on Linux, macOS, and Windows for Python 3.13. The `e2e` workflow runs nightly and on PRs that touch templates or the generator.

## Canvas TypeScript toolchains

The canvas npm workspace uses TypeScript 7 for `canvas-core` compilation and
declaration output. `canvas-vue` and `canvas-svelte` retain TypeScript 6 because
`vue-tsc`, Vue's SFC compiler, and `svelte-check` require its JavaScript API.
TypeScript 7 does not provide that API. The remaining framework migration is
tracked in [#357](https://github.com/cchifor/forge/issues/357).

Use Node 22 and install from the repository root. Commit `package-lock.json`
with dependency changes; npm installs both compiler majors, and a bare root
`tsc` can resolve TypeScript 6. Validate the workspace-specific compiler paths:

```bash
npm ci --no-fund --no-audit
npm run check:toolchains
npm run build
npm run typecheck
npm test
```

Build first so the framework packages can resolve `canvas-core` declarations.
All three workspace scripts are required and run in the canvas E2E job.

## Adding a new feature

- **New backend language**: see [backend authoring guide](docs/guides/adding-a-backend.md). The `BACKEND_REGISTRY` is the single source of truth.
- **New CLI flag**: add to `_build_parser` in `forge/cli/parser.py`, then use the configuration resolver/builders in `forge/cli/builder.py` and loading helpers in `forge/cli/loader.py`. Preserve documented precedence and structured errors.
- **Template change**: review the generated ownership and update impact, exact generator pin/fingerprint, and rendered native behavior. Adjust template version metadata where appropriate and test the emitted application; see [generated-code quality](docs/operations/generated-code-quality.md).
- **New error path**: use the appropriate `ForgeError` subclass from `forge.errors` and preserve the command's structured output/status contract. See [CLI exit statuses](docs/reference/cli.md#exit-status).

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
- Do not add AI co-author trailers. The required check rejects new commits with
  a `Co-authored-by:` line naming Claude.

## Opening a pull request

1. Branch from the current `main`:
   `git fetch upstream && git switch -c my-change upstream/main`.
2. Push the branch to your fork with `git push -u origin my-change`.
3. Open the pull request against `main` in `cchifor/forge`, with `gh pr create`
   or the **Compare & pull request** button on your fork.
4. Leave **Allow edits by maintainers** selected. `main` requires branches to be
   up to date before merging, and this lets a maintainer update yours.

GitHub holds workflow runs from first-time contributors until a maintainer
approves them, so checks on your first pull request can wait for a while. The
required `generated-quality` check runs on GitHub-hosted runners and uses no
repository secrets, so it behaves the same on a fork as on a branch here.

## Reporting issues

Include:
- `forge --help` output (confirms version)
- The exact `forge ...` command that triggered the issue
- For generation bugs: the contents of `forge.toml` from the generated project
- For template bugs: the rendered file's location relative to the project root
