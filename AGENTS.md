# Forge development

Use the shared `forge-platform` skill for platform generation and upgrades.
Generator code lives under `forge/`; emitted runtime templates live under
`forge/templates/` and `forge/features/*/templates/`.

Run `uv sync --locked --dev`, `make check`, and the generated-code quality
tests for changes to ownership, generation or coverage. Template changes
require testing rendered applications, not only template string assertions.

Generic generated code is extended through public ports and composition.
Do not lower coverage thresholds or change ownership to hide a failing gate.
Do not append AI co-author or session trailers to commits.
