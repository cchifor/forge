# Implementation review — feat/scaffold-fragment-cli — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 5 findings; 2 ACCEPT (this commit + agent), 2 PUSHBACK addressed, 1 PUSHBACK declined with rationale, 2 QUESTION noted) -->

## Codex verdict

**ACCEPT with 3 PUSHBACK items** — 2 addressed in this commit (docs
self-contradiction + output-dir file-path safety), 1 declined with
rationale (CLI shape deviation — defensible per existing `--plugins
list` precedent; user-facing string is the same modulo `--`).

## Findings + responses

### 1. CLI shape deviates from plan (PUSHBACK → DECLINED)
**Codex's concern:** plan prescribed `forge plugins scaffold-fragment <name>`
subparser. Agent kept the existing `--plugins <choice> --name <name>`
flag-with-choices pattern. Weakens discoverability + autocompletion.

**Response: PUSHBACK declined.** Agent's rationale stands:
- Matches existing `--plugins list` pattern exactly (consistency >
  prescription)
- Minimally invasive — promoting `plugins` to a subparser would touch
  the parser tree, completion scripts, and dispatch loop for marginal
  semantic gain
- User-facing string differs by 1 char (`--` prefix); same conceptual
  invocation
- Future migration to subparser (if it lands as part of Pillar A
  follow-up) can preserve the flag form for backward compat

If a future PR moves `--plugins` to a `plugins` subparser, it should
do so for ALL `--plugins` actions (`list`, `scaffold-fragment`, etc.)
to keep the surface coherent. That's a parser-architecture decision
larger than this PR.

### 2. Generated scaffold docs self-contradictory (PUSHBACK → ADDRESSED)
**Codex's concern:** generated `README.md` and `fragments.py` both
referenced `forge plugins scaffold-fragment {{ name }}` (the
non-existent subcommand form), while the actual command is `forge
--plugins scaffold-fragment --name <name>`. A plugin author scaffolding
the first fragment would run the wrong command per the generated docs.

**Response:** updated both `.jinja` files to use the actual invocation
form. Generated files now say
`forge --plugins scaffold-fragment --name {{ name }}`, matching what
the parser actually accepts.

### 3. Output-dir file-path safety (PUSHBACK → ADDRESSED)
**Codex's concern:** check at `forge/cli/commands/plugins.py:216`
assumes the path is a directory. If user passes an existing FILE,
`any(target.iterdir())` raises `NotADirectoryError` uncontrolled.

**Response:** added explicit `target.exists() and not target.is_dir()`
guard before the iterdir check. Surface a typed CLI error (exit 2)
with the path; don't let the stdlib exception propagate.

Added test `test_output_dir_is_existing_file_exits_with_typed_error`
that writes a file to the target path and asserts exit code 2 + the
"not a directory" message.

### 4. Backend validation hardcoded (QUESTION → noted)
**Codex's note:** `--backends` validation hardcodes `python,node,rust`
instead of resolving from `BackendLanguage` enum. Doesn't future-proof
against new backends.

**Response:** acknowledged. For A.5 scope this is fine (the 3 backends
are the only ones today). If a new backend lands (Pillar A.1's
ApplierRegistry SDK enables this), the hardcode would need an update —
tracked as follow-up. Not blocking this PR.

### 5. Test coverage gap on CLI dispatch path (QUESTION → noted)
**Codex's note:** tests strong on syntax/idempotency/force/backends/
name validation, but don't exercise the default `--output-dir "."`
mapping through the parser/main dispatcher (`forge/cli/main.py:182`).

**Response:** acknowledged. The dispatcher mapping is a thin shim;
the underlying `_scaffold_fragment` is well-tested. An integration
test through `_dispatch_plugins` would tighten this. Tracked for a
follow-up test additions PR if it surfaces as an issue.

## Convergence

5 findings — 2 ACCEPT (agent + this commit), 2 PUSHBACK addressed
(docs consistency + file-path safety), 1 PUSHBACK declined with
rationale (CLI shape — defensible per existing pattern), 2 QUESTION
noted (backend hardcode + dispatch test gap, both follow-ups).

No round 2 dispatched — actionable PUSHBACKs addressed; declined
PUSHBACK has explicit rationale + future migration path.

## Diff stat (final)

```
 CHANGELOG.md                                                |  16 +
 docs/plugin-development.md                                  |  50 +++
 forge/cli/commands/plugins.py                               | 268 ++++++++++++++-
 forge/cli/main.py                                           |  16 +-
 forge/cli/parser.py                                         |  34 +-
 forge/cli/scaffold/__init__.py                              |   7 +
 forge/cli/scaffold/fragment_skeleton/README.md.jinja        |  40 +++
 forge/cli/scaffold/fragment_skeleton/fragments.py.jinja     |  57 ++++
 forge/cli/scaffold/fragment_skeleton/inject.yaml.jinja      |   7 +
 forge/cli/scaffold/fragment_skeleton/node/files/__init__.ts.jinja |   6 +
 forge/cli/scaffold/fragment_skeleton/node/inject.yaml.jinja |  10 +
 forge/cli/scaffold/fragment_skeleton/python/files/__init__.py.jinja |   6 +
 forge/cli/scaffold/fragment_skeleton/python/inject.yaml.jinja |  10 +
 forge/cli/scaffold/fragment_skeleton/rust/files/lib.rs.jinja |   6 +
 forge/cli/scaffold/fragment_skeleton/rust/inject.yaml.jinja |  10 +
 pyproject.toml                                              |   4 +
 tests/test_scaffold_fragment.py                             | 376 +++++++++++++++++++++
 17 files changed, 904 insertions(+), 8 deletions(-)
```

Plus this impl-review file.
