# ADR-006: `forge.toml` provenance manifest as round-trip source of truth

- Status: Accepted
- Author: forge team
- Date: 2026-05-22
- Scope: `forge/sync/provenance.py`, the `[forge.provenance]` section of
  every generated project's `forge.toml`, and every flow that reads it —
  `forge --update`, `forge --harvest`, `forge --verify`,
  `forge --accept-harvested`, `forge --reapply-baseline`.

## Context

After `forge new` finishes, the generated project on disk contains a mix
of file kinds that forge needs to distinguish on the next `forge --update`:

| Kind | Owner | Behaviour on update |
|---|---|---|
| Base template file (unedited) | forge | Safe to re-emit. |
| Base template file (user-edited) | forge + user | Three-way merge inside `# forge:anchor` zones; conflict marker elsewhere. |
| Fragment-emitted file (unedited) | a fragment | Safe to re-emit if the fragment is still selected. |
| Fragment-emitted file (user-edited) | a fragment + user | Same merge rules as above. |
| User-authored file | user | Never touch. |
| File from a now-removed fragment | (was a fragment) | Eligible for `forge --remove-fragment` cleanup. |

The CLI flows depend on telling these apart cheaply and correctly. The
question is *how* the on-disk file announces its origin.

Three families of answer exist in the prior art:

1. **In-file headers / sentinels.** Each generated file gets a banner like
   `# generated-by: forge fragment=rag_qdrant version=1.0`.
2. **Git as the source of truth.** `git log --follow <file>` reveals which
   commit (and therefore which fragment, via PR metadata) emitted it.
3. **An out-of-band manifest.** One file alongside the project records the
   origin of every other file.

forge chose option 3: a `[forge.provenance]` section in the project's
`forge.toml`, recording one entry per emitted file with origin, content
hash, fragment + template version, and emission timestamp.

This ADR explains why.

## Decision driver

**The manifest must survive everything the user might do to the
project**, including:

- Reformat the codebase (Black, Prettier, ruff format).
- Move files between directories.
- Strip comments out wholesale.
- Squash, rebase, or amend git history.
- Copy-paste a file into a sibling project.
- Open the file in an IDE that auto-strips trailing whitespace, BOMs, or
  redundant blank lines.

Options 1 and 2 both fail at least one of those. Option 3 — one
out-of-band file, deliberately committed to the project — survives all of
them as long as the user doesn't delete `forge.toml` itself (an
intentional, easily noticed act, not an accidental side-effect of
running a formatter).

## Decision

**Every file forge writes is recorded in the project's `forge.toml`
manifest** with the following per-entry shape (schema version 2,
1.2.0+):

```toml
[forge.provenance."src/app/api/items.py"]
origin        = "fragment"        # "base-template" | "fragment" | "user"
sha256        = "ab12…"           # of emitted content, LF-normalised
fragment      = "rag_qdrant"      # null for base-template
fragment_version  = "1.0.0"
template_name     = "py-fastapi"
template_version  = "1.2.0"
emitted_at        = "2026-05-22T14:03:00Z"
```

Reads are direct TOML parsing. Writes go through
`ProvenanceLedger.record(...)` during a generation run and
`ProvenanceLedger.serialise()` at the end. On the next `forge --update`
or `forge --harvest`, `compare_to_disk(entry, path)` produces one of
`unchanged | user-modified | missing` by re-hashing the file and
matching against the recorded `sha256`. The classification feeds the
flow-specific logic (re-emit, three-way merge, surface as harvest
candidate, prompt for removal, etc.).

`forge.toml` itself is partitioned: `[forge]` and friends are
human-editable config; `[forge.provenance]` is mechanical and forge
will rewrite it wholesale on every update pass. The split is documented
in the file's leading comment.

### Hash normalisation

`sha256` is computed over the file's logical content with
`\r\n` normalised to `\n`. This means a file written on Windows and
later inspected on Linux yields the same digest — without forge having
to touch the on-disk bytes. This is the same trick git's `text`
attribute uses for the one operation we care about (integrity check).

### Schema versioning

`[forge.provenance_schema]` carries an integer `version`. v1 entries
(pre-1.2.0) lacked `fragment_version`, `template_name`,
`template_version`, `emitted_at`; the reader treats those fields as
"version unknown" rather than failing. Future schema bumps follow the
same back-compat-on-read policy.

## Alternatives considered

### Per-file headers / sentinels

Every emitted file starts with a banner comment that names its
fragment, version, and content hash.

Rejected because:

- **Visible noise.** A 6-line banner on every Python file is friction
  the user pays forever for a benefit they look at twice a year.
- **Lost on copy-paste.** A user who copies a file into a sibling
  project drops the header silently. The sibling project then can't
  participate in `forge --update`.
- **Lost on reformat.** `ruff format --select ALL`,
  `prettier --print-width`, or an IDE's auto-trim can mangle banner
  formatting in ways that break our regex parser.
- **Binary files have no comment syntax.** PNG icons, dat files, and
  protobuf descriptors all need to be tracked too. A header strategy
  needs a second mechanism for binaries — which is the manifest we'd
  have built anyway.
- **Doesn't track deletions.** A removed file leaves no header
  behind, so `forge --remove-fragment` has no way to know what to
  clean up.

We *do* keep `# forge:anchor <name>` zone markers inside selected
files — those are load-bearing for the three-way merge boundary. But
zone markers are a content-not-provenance signal; they say "user edits
inside here are first-class" rather than "this file was emitted by X."

### Git as the source of truth

`git log --follow <file>` reveals the commit that introduced it; PR
metadata or commit-message conventions can encode the fragment.

Rejected because:

- **Requires git.** forge runs in CI containers and developer machines
  that may or may not have a git repo. We don't want `forge --update`
  to fail because the user vendored the project into a non-git
  directory.
- **Squash / rebase erases history.** Standard PR workflows squash;
  `git log` then shows one commit per PR, not one per fragment. The
  provenance vanishes.
- **Slow.** `git log --follow` on a large repo per file is
  unacceptable for a CLI that updates hundreds of files in a single
  pass.
- **Doesn't survive a fresh clone with shallow history.**

### Sidecar `.forge-meta/` directory

One small JSON file per generated file, mirroring the project tree.

Rejected because:

- A second tree mirroring the project is more clutter than a single
  TOML file.
- Users keep deleting unfamiliar dot-directories. `forge.toml` looks
  like a config file (which it is) and gets committed by reflex.
- Atomicity: writing one file is one atomic rename; writing N files is
  N rename ops with N failure modes.

### Embed provenance inside `.copier-answers.yml`

Copier already writes its own answer file; piggyback on it.

Rejected because:

- `.copier-answers.yml` is *per render of one template*. forge composes
  fragments from multiple Copier subdirectories into one output;
  per-template answer files don't reflect the per-file ownership we need.
- The Copier answer file is part of Copier's stability contract — we
  don't want to layer forge-specific keys into it and risk colliding
  with a future Copier release.

## Consequences

### Positive

- **One file holds the entire round-trip contract.** Inspectable,
  diff-able, committable, greppable.
- **Survives reformatters and IDEs.** TOML is structured; whitespace
  inside a string field doesn't matter.
- **Tracks deletions and renames.** Files no longer in the manifest
  are eligible for `forge --remove-fragment`; files moved by the user
  are detected as "missing at recorded path."
- **Works for binary files.** TOML doesn't care; the manifest entry
  records a content hash either way.
- **Forward-compatible schema.** Version field plus read-side leniency
  lets us evolve without breaking old projects.

### Negative

- **`forge.toml` is load-bearing.** Deleting it loses round-trip
  ability — the next `forge --update` cannot tell user-edited files
  from clean ones. We mitigate with a leading-comment warning in every
  emitted `forge.toml` ("Do not delete; forge needs this to merge
  cleanly on updates") and a `forge doctor` check that flags a missing
  manifest in a project that has otherwise-recognisable forge layout.
- **Users must commit it.** A `.gitignore` that excludes `forge.toml`
  silently disables round-trip for that user's collaborators. We add a
  `.gitignore`-pattern check to `forge doctor` and document the
  requirement prominently in `docs/round-trip.md`.
- **Manifest format is a stability contract.** A breaking change to
  the schema requires an RFC (per the "RFC-cattle" policy
  in `CONTRIBUTING.md`). We've absorbed one bump (v1 → v2 in 1.2.0)
  with read-side back-compat; future bumps will follow the same path.
- **Hash mismatches require a story.** A user whose file
  legitimately diverged from the recorded baseline sees
  "user-modified" — which is *correct*, but the surfaced UX
  (prompts, conflict markers, harvest candidates) needs to feel
  helpful rather than scolding. Ongoing UX work, not an architecture
  flaw.

### Neutral

- TOML was chosen over JSON / YAML because `pyproject.toml` set the
  precedent for "Python project metadata in TOML" and the parsing /
  comment-preservation story is well-trod (tomlkit). No technical
  reason it couldn't be JSON; just less idiomatic.
- The manifest can grow large for big projects (hundreds of files).
  In practice, TOML parsing is fast and the file is read once per
  CLI invocation; no perceived perf cost so far. If this changes,
  the schema can be sharded by directory without breaking the
  read-side contract.

## References

- `forge/sync/provenance.py` — the recording + classification
  primitives. Read the module docstring for the canonical statement of
  this design.
- `docs/round-trip.md` — the user-facing invariants of bidirectional
  sync.
- `tests/test_harvest_invariants.py` — FR1-FR4 invariants that exist
  *because* of the manifest.
- ADR-003 (Copier over Cookiecutter) — the engine choice that makes
  bidirectional sync possible. This ADR explains the data structure
  that makes it correct.
