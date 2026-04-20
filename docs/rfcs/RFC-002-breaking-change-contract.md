# RFC-002: Breaking-change contract for 1.0 alpha

- Status: Accepted
- Author: forge team
- Created: 2026-04-20
- Updated: 2026-04-20
- Target: 1.0.0a1

## Summary

Every breaking change in the 1.0 alpha series must (a) appear in `CHANGELOG.md` under `### Breaking`, (b) include migration instructions in `UPGRADING.md`, and (c) ship with a `forge migrate-<name>` codemod when mechanically applicable. This RFC defines what "mechanically applicable" means and what the codemod contract is.

## Motivation

The 1.0 plan is a clean-break — users will face breaking changes at every phase boundary. Without a contract:

- Users get stuck on old alphas because no migration path exists.
- Breaking changes land undocumented and are discovered at runtime.
- Codemods are inconsistent — some idempotent, some not, some destructive, some not.

A single contract applied uniformly makes the alpha series navigable.

## Design

### What counts as breaking

A change is breaking if **any** of:

1. A `forge` CLI flag is removed or renamed.
2. The `forge.toml` schema changes in a way that old files can't be loaded.
3. A file path or API in a generated project changes such that `forge --update` can't apply cleanly without user action.
4. A runtime dependency is bumped such that it drops a Python/Node/Rust version forge previously supported.
5. A public API of `forge` (anything not prefixed `_`) is removed or changes signature.

### Required artifacts per breaking change

Every breaking change ships with:

- **CHANGELOG entry** under `### Breaking`, format:
  ```
  - **<short title>** — <one-sentence description>. Migration: <one-sentence or link to UPGRADING.md section>.
  ```
- **UPGRADING.md section** under the version heading, with step-by-step before/after code samples.
- **Codemod** (if mechanically applicable) named `forge migrate-<name>` invokable from the CLI.
- **Regression test** in `tests/migrations/test_migrate_<name>.py` that takes an old-format project fixture, runs the codemod, and asserts the output matches a committed golden snapshot.

### Codemod contract

A `forge migrate-<name>` codemod must:

1. **Idempotent** — running twice is a no-op the second time.
2. **Reversible via git** — the codemod operates on files only; no external state (databases, remote services).
3. **Safe on partial state** — if a previous migration ran halfway, re-running completes without corruption.
4. **Verbose by default** — print each file touched and what changed.
5. **`--dry-run` supported** — print the diff without applying.
6. **Exit non-zero on any conflict** — don't silently skip; surface the conflict so the user can resolve.

Signature:

```python
def run(project_root: Path, *, dry_run: bool = False, quiet: bool = False) -> MigrationReport:
    """Apply the migration to the project. Return a report of files changed."""
```

### Umbrella `forge migrate`

A `forge migrate` umbrella command runs all applicable migrations in dependency order:

```bash
forge migrate                    # runs all pending migrations in order
forge migrate --dry-run          # preview
forge migrate --only entities    # run only `forge migrate-entities`
forge migrate --skip ui-protocol # run everything except this one
```

The umbrella reads `forge.toml`'s `forge.version` field, consults a hard-coded migration table (ordered list of `(from_version, to_version, migrator)` tuples), and applies each applicable one.

### When a breaking change cannot have a codemod

If a breaking change cannot be mechanically migrated (e.g. user must choose between two new options, or the template structure changes fundamentally), the `UPGRADING.md` entry **must**:

1. State explicitly "no codemod — manual migration required".
2. Provide a complete step-by-step guide with copy-pasteable commands.
3. Be reviewed by at least one person other than the author.

## Alternatives considered

### No codemod requirement — documentation only

Lighter maintenance burden, faster shipping. Rejected because every alpha without a codemod pushes the migration cost onto users, and the 1.0 path has many alphas. The codemod investment pays back once the user base is > 3 projects.

### Deprecation-with-warning instead of hard breaks

Ship both old and new APIs side-by-side with deprecation warnings, remove old APIs in the next alpha. Rejected for the alpha phase because it doubles the test matrix and the alpha target audience is explicitly breakage-tolerant. Reserve deprecation cycles for post-1.0 minor bumps (this is stated in `RELEASING.md`).

## Drawbacks

- Codemod authoring is expensive — every breaking change takes longer to ship.
- Golden-snapshot tests for codemods create merge friction when fixtures need to update.
- Umbrella `forge migrate` becomes a complex piece of infrastructure over time.

Mitigation: the Phase 4.5 "generator testing upgrade" item explicitly includes codemod regression tests in its scope, so the infrastructure cost is absorbed there.

## Open questions

- Should codemods be versioned independently (e.g. `migrate-entities@1.2.0`), or always tied to the forge release they shipped with? **Resolved: tied to release.** Independent versioning adds complexity without benefit at this scale.
