# Working in a Forge project

Read `forge.toml` for provenance and `.forge/quality.json` for the pinned
generation recipe. Discover the actual services and frontend paths with
`forge --quality inventory --project-path .`.

Use the shared [Forge platform skill](.agents/skills/forge-platform/SKILL.md).
Claude discovers the same instructions under `.claude/skills/forge-platform/`.

Generated runtime, contracts, SDKs and middleware are protected. Extend public
ports from application modules; register adapters in the composition root.
Do not change generated internals, shadow generated packages, or monkey-patch
their members. Application routes, domain models and services marked
`scaffold` are editable. Inspect ownership before editing.

Run architecture, unit, integration, E2E and coverage gates after changes.
A missing suite is a failure. New executable lines must have coverage strictly
greater than 80% for each service, frontend and shared runtime.
Use a real Git base for changed-code checks; do not weaken reports or exclusions.

Preview upgrades with `forge --plan-update --project-path . --json`, then
run `forge --update --project-path . --json`. Keep custom behavior in separate
files. Resolve scaffold conflicts with `forge --quality resolve --subject
RELATIVE_FILE --resolution keep|replace --project-path .`; `keep` retains a
reviewed manual merge. Run the update again to finish.

Use frozen installs after reviewing and committing dependency locks:
`forge --quality install --project-path .`. Explicit dependency changes use
`forge --quality lock --project-path .` first. See the skill for service
technology recommendations and capability validation.

Preserve the user's Git identity. Do not add Claude or other AI co-author
trailers or assistant attribution to commits and pull requests.
