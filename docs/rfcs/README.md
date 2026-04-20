# forge RFCs

Request-for-comment documents for forge design decisions.

## When to write an RFC

Write an RFC for any of:

- A breaking change to the public API (CLI flags, `forge.toml` schema, plugin contract)
- A new subsystem that will outlive a single PR (codegen pipeline, plugin host, adapter pattern)
- An architectural decision with multiple viable options where the choice is not obvious
- A cross-cutting concern affecting more than one template (e.g. adopting a new framework)

Skip an RFC for: bugfixes, docs, test additions, mechanical refactors with no design room.

## Process

1. Open a PR adding `docs/rfcs/RFC-NNN-short-slug.md` with **Status: Draft**.
2. Tag reviewers; target at least one round of feedback.
3. Update to **Status: Accepted** when consensus forms, or **Rejected** with a summary of why.
4. Accepted RFCs are the specification; implementation PRs reference the RFC number.

## Template

```markdown
# RFC-NNN: Title

- Status: Draft | Accepted | Rejected | Superseded by RFC-MMM
- Author: <name>
- Created: YYYY-MM-DD
- Updated: YYYY-MM-DD
- Target: 1.0.0aX

## Summary

One paragraph. What the RFC proposes and why.

## Motivation

What problem this solves. What user pain point or internal fragility this addresses.

## Design

The proposal. Include code samples, file-tree diagrams, and migration notes.

## Alternatives considered

What else was on the table and why the chosen design won.

## Drawbacks

Costs and risks of the proposal.

## Open questions

Things the reviewers should weigh in on.
```

## Current RFCs

| # | Title | Status | Target |
|---|---|---|---|
| 001 | Versioning and branching policy | Accepted | — |
| 002 | Breaking-change contract for 1.0 alpha | Accepted | 1.0.0a1 |
| 003 | Published-package naming and ownership | Draft | 1.0.0a4 |
| 004 | Release rehearsal before 1.0.0 | Accepted | 1.0.0rc1 |
