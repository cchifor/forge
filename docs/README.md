# Forge documentation

Forge generates and updates full-stack projects from a configuration and a
registry of composable features. Start with the platform overview to understand
the system, then choose a guide for the work you want to do.

| I want to… | Read |
| --- | --- |
| Understand the platform, runtime, and data flows | [Platform overview](architecture/overview.md) |
| Generate and run my first application | [Getting started](guides/getting-started.md) |
| Choose languages and service boundaries | [Technology selection](guides/technology-selection.md) |
| Generate a multi-service or tenant-aware system | [Platform presets](guides/platforms.md) |
| Use Forge with Codex or Claude | [Agent workflow](guides/agentic-usage.md) |
| Add business behavior without breaking regeneration | [Customize and upgrade](guides/customization.md) |
| Enforce architecture and test coverage | [Generated-code quality](operations/generated-code-quality.md) |
| Find a command, option, or support limitation | [Reference](reference/README.md) |
| Deploy, diagnose, or maintain a project | [Operations](operations/README.md) |
| Change Forge itself or develop a plugin | [Maintainer onboarding](guides/maintainer-onboarding.md), [plugin guide](guides/plugins.md) |
| Understand why a design was chosen | [Decisions, RFCs, and plans](plans/README.md) |

## Documentation structure

```text
docs/
├── README.md                 # Start here: tasks and navigation
├── architecture/             # Current system, generator, and sync explanations
├── guides/                   # Task-oriented human and agent workflows
├── reference/                # CLI, capability limits, MCP, and telemetry
├── operations/               # Quality gates, deployment, troubleshooting, runbooks
├── plans/                    # Index of implementation plans and historical reviews
├── architecture-decisions/   # Numbered ADRs: rationale and consequences
├── rfcs/                     # Numbered proposals: retain each recorded status
├── FEATURES.md               # Generated option catalog; do not hand-edit its catalog
├── auth-architecture.md      # Detailed auth contract at a stable tested path
├── coverage-policy.md        # Generator coverage ratchet, separate from app coverage
└── SDK_CHANGELOG.md          # Plugin SDK compatibility history
```

The four reference files at the root retain paths used by generation, tests, and
existing consumers. Short compatibility pages also preserve paths embedded in
CLI diagnostics, generated templates, and published references. They link to the
canonical pages in the directories above; new documentation should link directly
to those canonical pages.
The dated implementation records remain in the repository's [plans](../plans/)
directory; the [plan index](plans/README.md) connects them to current documentation.

## Reading status correctly

Current guides describe the checked-in implementation. The live option registry
and `forge --config stack.yaml --plan --json` determine whether a particular
combination is supported. An RFC's acceptance records a design decision; it does
not imply that every proposed feature shipped. Dated reports and CI snapshots
are historical evidence, not a statement about today's test results.

See [capabilities and limitations](reference/limitations.md) for the supported
technology matrix, planned surfaces, and validation boundaries. The generated
Compose stack is a development starting point; follow the
[deployment guide](operations/deployment.md) before exposing it outside local
development.

## Maintaining these docs

Put procedures in `guides/`, explanations in `architecture/`, exact command and
format details in `reference/`, and operational checks in `operations/`. Link to
one canonical explanation rather than copying it into every guide. Preserve
numbered ADRs/RFCs and dated plans; update their indexes when implementation
changes their relevance. Use Mermaid for diagrams that should render on GitHub,
and keep diagrams next to the behavior they explain.

When moving a page, update repository links and the relevant checks in
[`tests/test_doc_truth.py`](../tests/test_doc_truth.py). Option catalog changes
come from [`tools/gen_features_doc.py`](../tools/gen_features_doc.py). Do not
change a historical proposal into a current product promise.
