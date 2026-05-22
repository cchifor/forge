# ADR-008: Codex review runs in a separate git worktree

- Status: Accepted
- Author: forge team
- Date: 2026-05-22
- Scope: the `codex-toolkit` plugin's dispatcher (the entry point invoked
  by the `codex-reviewed-planning` skill for both plan-review and
  implementation-review phases). Not forge runtime code — this ADR
  documents a *contributor workflow* decision that has shaped how forge
  PRs land since the plan-review loop was adopted.

## Context

Non-trivial forge work goes through a two-phase Opus ↔ Codex review loop:

- **Phase A** — *plan review*. Opus drafts a plan in
  `.claude/plans/<name>.md`. Codex critiques it in a read-only checkout
  and emits inline `<!-- codex: ... -->` markers. Opus addresses each
  marker. Loop continues up to 2 rounds, then escalates to the human
  if disagreement persists.
- **Phase B** — *implementation review*. After the plan is implemented,
  Codex re-reads the changes in the same way and surfaces issues for a
  second round.

The dispatcher that runs Codex has a choice: invoke `codex exec` against
the user's current working tree, or against a freshly-checked-out
sibling worktree off `HEAD`.

The dispatcher uses the sibling-worktree approach. This ADR explains
why, because the cost (~5 seconds of extra git work per invocation)
is visible enough that a contributor will reasonably ask whether it
could be skipped.

## Decision driver

**Codex's review must operate on a stable, committed snapshot and must
not touch the user's working tree.** Three constraints push toward the
worktree approach:

1. **Codex may write.** Although the review profile is read-only, the
   profile is set per invocation. A misconfigured profile, a `bash`
   tool call inside Codex's session, or a future review template that
   asks Codex to apply patches directly would all expose the user's
   working tree to writes Opus didn't sanction.
2. **The user keeps editing during review.** Opus dispatches Codex and
   keeps working — sometimes on the very file Codex is reading. If
   Codex were pointed at the live tree, every saved edit would shift
   the lines Codex's markers reference, and the markers would land at
   the wrong positions when Opus reads the result back.
3. **Reviews should be reproducible.** "Codex reviewed `HEAD`" is a
   clear contract. "Codex reviewed whatever was on disk at some moment
   during a 90-second window" is not.

A git worktree off `HEAD` solves all three: it's a stable snapshot, it's
physically separate from the user's checkout, and any writes Codex makes
land in a sandbox that the dispatcher cleans up.

## Decision

**The dispatcher creates a sibling worktree under
`.claude/worktrees/codex-{plan,impl}-review-<timestamp>/` pointed at the
current `HEAD`, runs `codex exec` against that worktree, captures the
review output via `--output-last-message`, and removes the worktree
afterward.**

Concretely:

```
git worktree add -d .claude/worktrees/codex-impl-review-20260521-201347 HEAD
codex exec --profile impl-review \
  --working-directory .claude/worktrees/codex-impl-review-20260521-201347 \
  --output-last-message .claude/worktrees/.../codex-output.md \
  "<review prompt>"
git worktree remove --force .claude/worktrees/codex-impl-review-...
```

The dispatcher's return value is the captured `--output-last-message`
file path; Opus reads it back in the main worktree and processes the
inline `<!-- codex: ... -->` markers.

### Cleanup

The dispatcher unconditionally removes the worktree on completion
(success, failure, or interrupt). The `.claude/worktrees/` directory is
in the project's `.gitignore`, so leaked worktrees (e.g. if the process
is `kill -9`'d mid-run) don't pollute commits. A periodic
`git worktree prune` on the main checkout sweeps dangling
administrative state.

### Windows quirk

On Windows, the dispatcher wraps the `codex exec` call in
`cmd /c "... < NUL"` to work around a known v0.130 stdin-EOF hang. This
is orthogonal to the worktree decision but worth recording in the same
place — the worktree approach is what allows the `< NUL` redirection
trick to work uniformly (the cmd shim's `cwd` is the worktree, not the
user's terminal `cwd`).

## Alternatives considered

### Run Codex against the user's working tree

Skip the worktree; pass the user's project root as `--working-directory`.

Rejected because:

- **Codex writes would land in the user's WIP.** Even if the current
  review profile is read-only, the next one might not be. Defence-in-depth
  matters when the alternative is silent corruption of unrelated work.
- **The user keeps editing during the review.** Codex's
  `<!-- codex: ... -->` line markers would land at the wrong positions
  by the time Opus reads them back if intervening edits moved the
  lines.
- **Codex's view of the world becomes nondeterministic.** What if the
  user runs a formatter mid-review? Codex sees one version; Opus
  processes the result against a different version. The markers no
  longer make sense.
- **Hard to debug a bad review.** "Re-run that review against the same
  state" is impossible if the state was the live tree.

### Run Codex against a stash

`git stash create` produces a tree object; check out a detached HEAD at
that tree, run Codex there.

Rejected because:

- Stash objects don't carry untracked files (without `-u`); the
  worktree does.
- Stash-then-restore is cosmetically intrusive — it touches the user's
  index even when nothing is actually staged.
- A worktree is the right abstraction *because* it's what git ships
  for "another checkout of the same repo at a different ref"; reusing
  stash semantics here is fighting the tool.

### Clone the repo into `/tmp`

Full clone, hard-coded `--depth 1`, into a scratch path.

Rejected because:

- A clone copies object storage; a worktree shares it. For a repo
  with sizeable history, the clone is much slower.
- A clone loses the local-only refs and the `.gitignore` semantics
  (file modes, sparse checkout, etc.).
- Cleanup is harder — `/tmp` outside the repo doesn't get swept by
  `git worktree prune`.

### Run Codex in a Docker container with the repo mounted read-only

Mount the project at `/workspace:ro`, run Codex inside.

Rejected because:

- Adds a container dependency to every plan-review invocation. The
  dispatcher already optimises for low latency (~5s, not ~30s).
- Read-only mount doesn't help with the "captured output writes" part —
  we still need a writable scratch for `--output-last-message`. The
  worktree gives us both for less.
- A container layer between Opus and Codex adds another failure mode
  (image not present, daemon not running, mount failure) for the same
  guarantee a worktree provides natively.

## Consequences

### Positive

- **Hermetic review.** Codex sees `HEAD` and only `HEAD`. The user's
  WIP is invisible to it. Reproducible by re-running against the same
  commit.
- **No risk of clobbering WIP.** Whatever Codex does inside the
  worktree, the user's main checkout is untouched.
- **Cheap on disk and time.** Worktrees share object storage with the
  parent repo; only metadata is duplicated. The ~5-second cost is
  dominated by the `git worktree add` invocation, which is
  comparable to opening a new file in an IDE.
- **Composable with parallel review.** Plan-review and impl-review (or
  multiple concurrent reviews of independent plans) can each have their
  own worktree without coordination.

### Negative

- **Codex can't reference uncommitted changes.** A review prompt that
  refers to "the change you're about to commit" has to be staged or
  committed first. In practice this lines up with how the loop is used
  — Phase B reviews a committed implementation, and Phase A reviews a
  committed plan file. A user trying to get Codex feedback on
  truly-uncommitted edits has to commit them first (or stash → commit
  → revert).
- **~5 seconds per invocation.** `git worktree add` is fast but not
  free. For interactive iteration, this latency adds up across a
  two-round loop (4 reviews per task, ~20s of git overhead per task).
  Worth it for the guarantees above.
- **Disk usage grows if cleanup fails.** A SIGKILL'd dispatcher can
  leak a worktree directory plus administrative state under
  `.git/worktrees/`. Mitigated by periodic `git worktree prune` and the
  `.gitignore` entry for `.claude/worktrees/`. A non-leaky cleanup
  story is on the toolkit's backlog.
- **Doesn't help with cross-repo reviews.** A Codex review that needs
  to see two repositories simultaneously can't be solved by a single
  worktree. We have not hit this in practice; the workflow assumes
  one-repo-per-review.

### Neutral

- The decision is reversible per-invocation. A future "fast path" for
  trivial reviews could skip the worktree and accept the trade-offs,
  but the default is the worktree because the cost is small and the
  invariants matter.
- This decision is documented as a forge ADR (rather than a
  codex-toolkit-internal note) because every contributor to forge sees
  the worktree at `.claude/worktrees/` and may wonder why it's there.
  An ADR is the right place to point them at.

## References

- `codex-toolkit` plugin (`~/work/claude/plugins/codex-toolkit/`) —
  the `codex-reviewed-planning` skill that documents the two-phase
  loop and the dispatcher contract.
- The `codex-run` helper documented in
  `~/.claude/projects/-workspace-c4/memory/codex-run-helper.md` — the
  underlying invocation pattern.
- Conventional locations: `.claude/worktrees/` (gitignored;
  dispatcher-owned scratch); `.claude/plans/` (committed; the artifact
  Codex reads).
- forge `CONTRIBUTING.md` — the codex-review workflow is invoked
  here implicitly for non-trivial plans.
