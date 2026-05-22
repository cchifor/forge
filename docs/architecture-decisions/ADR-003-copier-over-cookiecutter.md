# ADR-003: Copier over Cookiecutter as the template engine

- Status: Accepted
- Author: forge team
- Date: 2026-05-22
- Scope: the `forge new` / `forge update` codegen pipeline (every fragment renders through Copier)

## Context

forge is, at its core, a project generator. The default choice in the Python
ecosystem is [Cookiecutter](https://github.com/cookiecutter/cookiecutter): it
has the largest template library, the most mind-share, and almost every
"start a new Python project" tutorial reaches for it first. A new contributor
opening forge for the first time will routinely ask "why are we not using
Cookiecutter?"

forge does not use Cookiecutter. It uses
[Copier](https://github.com/copier-org/copier) for every render pass, both
the initial `forge new` and the ongoing `forge update --mode merge`,
`forge update --reapply-baseline`, `forge harvest --accept-harvested`, and
`forge verify` flows.

This ADR records why the choice was made and what we accept in return.

## Decision driver

**Copier supports `copier update`. Cookiecutter does not.**

That single capability — re-rendering a template over an already-generated
project, with three-way conflict resolution between the old template output,
the new template output, and the user's edits — is the entire foundation of
forge's bidirectional-sync story. Specifically:

- `forge update --mode merge` re-runs the template against an existing
  project, preserves user edits inside `# forge:anchor` zones, and falls back
  to git-merge-style conflict markers when both sides changed the same
  region.
- `forge update --reapply-baseline` walks back to the recorded answer set,
  re-emits the original baseline, then re-applies the user's diff on top.
- `forge harvest` reads the current generated tree and back-propagates user
  edits inside marked regions into the project's `forge.toml` provenance so
  the next `update` keeps them.
- `forge verify` does a dry-run render and compares to the on-disk file,
  reporting drift without writing.

Cookiecutter's design is intentionally one-shot: render once, throw the
template state away, leave you with a normal project. There is no built-in
notion of "what answers did this user pick last time?" and no concept of
"re-run me against my own output." The community has built half-solutions
(`cruft`, `cookieplone`, custom `post_gen_project.py` hacks) that essentially
re-implement what Copier ships natively. We considered building forge on top
of `cruft` (which wraps Cookiecutter to add update support) and rejected it
for the reasons in *Alternatives considered* below.

## Decision

**forge depends on Copier as a hard dependency and uses its template
format, answer-file convention (`.copier-answers.yml`), and `copier update`
machinery for every regeneration pass.** Fragments are authored as Copier
templates with Jinja extensions; conditional file emission uses Copier's
`_skip_if_exists` and `_subdirectory` keys; multi-prompt flows use Copier's
`questions.yml`.

forge layers its own machinery on top:

- A higher-level **option** model (`forge/options/_registry.py`) that drives
  Copier's answer file rather than the user editing the YAML directly.
- A **fragment registry** (`forge/fragments/_registry.py`) that composes
  multiple Copier subdirectories into one render plan, with explicit
  dependency resolution between fragments.
- A **provenance manifest** (`forge.toml`, see ADR-006) layered alongside
  `.copier-answers.yml` to record which fragment owns which file — Copier's
  built-in answer file is per-template, not per-file.
- A **zoned-injection system** (`# forge:anchor` markers) that lets forge
  modify files inside Copier-rendered output without forcing them into the
  Copier template, so adjacent fragments can share a file.

The user never sees Copier directly. They see `forge new`, `forge update`,
`forge verify`. Copier is the engine.

## Alternatives considered

### Cookiecutter

Larger ecosystem (~10x as many public templates), more familiar to Python
engineers, larger plugin community.

Rejected because:

- No native update story. The whole `--update / --harvest / --verify`
  surface would need to be hand-built on top, including the three-way merge
  logic that Copier already ships.
- The Cookiecutter template format would still need extending for the
  multi-fragment composition forge needs — Cookiecutter assumes one template
  per project, not 74 fragments layered together.
- The community has migrated to Copier for "evergreen template" use cases
  (Pylon, copier-pdm, copier-poetry, fastapi-mvc); we'd be adopting a less
  active dialect.

### cruft (Cookiecutter + update layer)

Wraps Cookiecutter with diff-based updates by recording the rendered output
hash and replaying user diffs on regenerated output.

Rejected because:

- It re-implements Copier's three-way merge with a thinner conflict model
  (line-level only, not zoned).
- Maintenance burden: cruft has one primary maintainer, and the update layer
  is the most complex part of the codebase. Copier's update machinery has
  significantly more contributors and test coverage.
- We would be adopting two layers (cruft + Cookiecutter) when one (Copier)
  ships the same capability with a smaller surface.

### Build our own engine

Roll a template engine purpose-built for fragment composition.

Rejected because:

- Templating is a deep problem. Jinja edge cases, file-permission
  preservation, symlink handling, Windows path quirks, binary-file passthrough
  — all already solved in Copier and we have no differentiating reason to
  re-solve them.
- "Build our own" is a multi-year detour with zero user-visible payoff.

## Consequences

### Positive

- **Bidirectional sync works.** `forge update` is the headline feature; it
  exists because Copier exists.
- **Answer file is a public contract.** `.copier-answers.yml` is portable —
  a user can move their project, run `copier update` directly without forge
  installed, and the template will re-render. (This is an escape hatch, not
  a recommendation; forge's higher-level options layer is where users should
  operate.)
- **Smaller forge surface.** We don't own the template-rendering loop, the
  merge algorithm, the answer-file format, or the conflict-marker protocol.
  Bug fixes in those areas land upstream and we pick them up on the next
  `pip install -U copier`.

### Negative

- **Smaller template ecosystem.** Cookiecutter has roughly 10x as many
  public templates. We accept this; forge's templates are first-party and
  the gap doesn't affect users.
- **Tied to Copier's answer-file format.** `_copier_*` keys are a stability
  contract we don't control. Major Copier releases occasionally rename or
  restructure them, requiring forge migrations (we've absorbed two so far,
  Copier 6 → 7 → 8).
- **Harder to upstream contributions.** A contributor who knows Cookiecutter
  has to learn Copier's slightly different idioms (`{{ _copier_conf }}`,
  `_subdirectory`, `migrations`). The learning curve is real but shallow —
  a half-day of reading the Copier docs.
- **Locked into Jinja2.** Copier hardcodes Jinja; we cannot offer
  template-author choice (Mustache, Handlebars, etc.). This has never come
  up as a user request and isn't expected to.

### Neutral

- forge's higher-level abstractions (options, fragments, provenance) mean
  that "Copier the engine" is mostly invisible to end users. A future
  replacement (if Copier were ever abandoned) would be feasible at the cost
  of re-implementing the update / merge layer — non-trivial but bounded.

## References

- [Copier documentation](https://copier.readthedocs.io/) — particularly the
  `update` and `migrations` sections.
- [Cookiecutter vs Copier comparison](https://copier.readthedocs.io/en/stable/comparisons/)
  (upstream's own writeup; opinionated but accurate on the update-story
  gap).
- `forge/sync/forge_to_project/` — forge's update pipeline that sits on top
  of `copier update`.
- ADR-006 (provenance manifest) — explains why `forge.toml` exists alongside
  `.copier-answers.yml`.
