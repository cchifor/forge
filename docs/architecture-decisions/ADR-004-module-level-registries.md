# ADR-004: Module-level registries over an explicit DI container

- Status: Accepted
- Author: forge team
- Date: 2026-05-22
- Scope: `forge/options/_registry.py`, `forge/fragments/_registry.py`,
  `forge/config/_backend.py` (BACKEND_REGISTRY), `forge/services/registry.py`,
  `forge/plugins.py` (COMMAND_REGISTRY)

## Context

forge composes a generated project from three static catalogues:

| Catalogue | Module-level singleton | Roughly how many |
|---|---|---|
| Options (user-facing knobs) | `OPTION_REGISTRY: dict[str, Option]` | ~47 |
| Fragments (units of templated output) | `FRAGMENT_REGISTRY: _FragmentRegistry` | ~74 |
| Backends (language targets) | `BACKEND_REGISTRY: dict[..., BackendSpec]` | 3 |
| Services (full-app templates) | `SERVICE_REGISTRY: dict[str, ServiceTemplate]` | a handful |
| Plugin commands | `COMMAND_REGISTRY: dict[str, Callable]` | grows with plugins |

All five are plain module-level dicts (or thin wrapper classes around a
dict) populated at import time by registration calls in sibling modules.
A new contributor coming from a typical service codebase will notice this
immediately and ask: "Why are we not using a DI container?
[punq](https://github.com/bobthemighty/punq),
[dependency-injector](https://python-dependency-injector.ets-labs.org/),
[dishka](https://dishka.readthedocs.io/), or our own `Container` class
would be the conventional answer."

The question is sharper because forge *does* use dishka inside its
generated FastAPI projects (ADR-002) — so the team is comfortable with DI
containers; we just don't reach for one inside forge itself.

This ADR records why.

## Decision driver

**The contents of all five registries are STATIC at runtime.** Nothing
gets added after the import-time registration pass completes. There are
no per-request lifecycles, no scoped factories, no transient-vs-singleton
distinctions. A `dict` is the right data structure for a thing whose
shape is fixed by import time.

A DI container's value proposition is:

1. **Wiring complex graphs.** N services that depend on each other in
   non-trivial ways. forge has none — the registries are flat lookup
   tables.
2. **Managing lifecycles.** Request-scoped vs singleton vs transient.
   forge runs as a CLI; everything is process-scoped.
3. **Lazy instantiation.** Construct expensive objects on first use.
   `Option` / `Fragment` / `BackendSpec` are tiny dataclasses; the cost
   of constructing them all eagerly is microseconds.
4. **Test-time substitution.** Swap a real implementation for a fake.
   forge tests do this by monkey-patching the dict directly — a 2-line
   `monkeypatch.setitem(OPTION_REGISTRY, "foo", fake_option)` — which is
   no harder than container-based mocking.

None of those four motivations apply to a CLI codegen tool with five flat
catalogues. Reaching for a container would buy us an indirection layer,
a registration DSL, lifetime semantics we don't use, and a new dependency,
in exchange for nothing.

## Decision

**Each catalogue is a module-level `dict` (or a thin wrapper class
holding a dict), populated at import time by sibling modules.** Reads
are direct attribute access. Writes go through a `register_*()` helper
that enforces uniqueness and (for FRAGMENT_REGISTRY) a one-shot freeze
at startup audit time (Epic I).

### Concretely

- `forge/options/_registry.py` defines `OPTION_REGISTRY: dict[str, Option]`
  as an empty dict at module scope. `forge/options/__init__.py` imports
  every per-namespace module (`observability.py`, `reliability.py`,
  `knowledge.py`, …) and each calls `register_option(...)` at import.
  After `forge.options` has been imported once, the registry is fully
  populated and never mutated again in production.
- `forge/fragments/_registry.py` is similar but wraps the dict in a
  `_FragmentRegistry` class so we can hook `__setitem__` with the
  freeze-after-startup audit (Epic I, defensive against
  `register_fragment` being called after the CLI is past its bootstrap
  phase — which would indicate a bug in lazy plugin loading).
- `forge/config/_backend.py` ships `BACKEND_REGISTRY` as a dict literal
  — Python, Node, Rust are known at module-definition time; there is no
  registration ceremony.
- `forge/services/registry.py` and `forge/plugins.py` follow the same
  pattern.

### Plugin extension

Plugins extend the registries by importing forge and calling the
`register_*()` helpers from their own entry-point modules — exactly the
pattern an in-tree namespace module uses. Plugin discovery is explicit
(`forge plugins load <name>` or `[project.entry-points."forge.plugins"]`
in `pyproject.toml`) so the import-time guarantee still holds: once the
plugin's entry-point fires, registration is done.

## Alternatives considered

### Full DI container (dishka, punq, dependency-injector)

Standard Python DI, with `@provide` decorators, scopes, and a
container instance threaded through the call stack.

Rejected because:

- All five registries are flat lookup tables; a container's
  DAG-resolution engine is unused.
- We'd introduce a runtime dep with its own API surface, version
  policy, and learning curve for contributors.
- The CLI startup hit of constructing a container, registering five
  catalogues' worth of providers, and resolving them on first use is
  larger than the dict-literal approach we have now.
- We use dishka inside generated FastAPI projects (ADR-002) because
  *those* have a request lifecycle. forge does not.

### Single global `ForgeContext` object

One mutable god-object holding all five registries as attributes.
Passed to every function that needs them.

Rejected because:

- Threading `ctx` through every call site is the boilerplate a container
  was supposed to remove.
- Module-level dicts achieve the same singleton semantics with `import`
  as the lookup mechanism — which is what Python is good at.

### Class-based singletons

`class OptionRegistry: _instance = None` style, with `OptionRegistry.instance().get(name)`.

Rejected because:

- A class wrapping a dict is just a dict with extra `.` characters.
- Static-analysis tools (mypy, ty, pyright) narrow `dict[str, Option]`
  better than a method-call chain.
- Test mocking via `monkeypatch.setitem` is harder against an opaque
  singleton; against a module-level dict it's one line.

### Lazy plugin discovery via entry-points walk-on-startup

Auto-discover and register all installed plugins on every forge import.

Rejected because:

- Implicit plugin loading is a known footgun (slow CLI startup, surprise
  conflicts, hard-to-debug import errors). We opted for explicit
  `forge plugins load` to keep import-time deterministic.
- Once explicit, the registration model collapses back to "call
  `register_*()` from an explicit entry-point module" — exactly what
  module-level dicts already support.

## Consequences

### Positive

- **Static-analysis friendly.** `OPTION_REGISTRY["rag.backend"]` returns
  `Option` to mypy/ty/pyright with zero ceremony. A container's
  `container.get(OptionRegistry).get("rag.backend")` chain is harder to
  type and easier to break.
- **Trivial test mocking.** `monkeypatch.setitem(OPTION_REGISTRY, "foo",
  fake)` works in every test, no fixture plumbing needed.
- **Zero runtime dependencies for the registries.** The container family
  (`punq`, `dishka`, `dependency-injector`) is not in our `pyproject.toml`.
- **Fast CLI startup.** No container construction, no
  provider-resolution pass; the registries are populated as the import
  graph is walked, which Python is already doing.
- **Trivial mental model.** A new contributor reads
  `forge/options/__init__.py`, sees imports, follows them, and within
  five minutes understands the whole option surface.

### Negative

- **Registration must happen at import time.** There is no lazy
  registration path. A plugin that wants to defer registration until
  after some runtime check has to either (a) register eagerly and
  short-circuit its option's `enables` map, or (b) gate its `register_*()`
  call inside a `forge plugins load <name>` invocation. We accept this;
  the alternative (a hot-reloadable container) is more complexity than
  the use case warrants.
- **No per-call lifecycle hooks.** Module-level dicts can't run code on
  "first lookup" or "registry-wide reset." We have not needed either; if
  we ever do, we'd add a thin wrapper class (as `_FragmentRegistry`
  already does for its freeze hook).
- **Mock injection is monkey-patching.** Tests mutate the global dict
  inside a `monkeypatch` fixture. This works fine in pytest but is
  cosmetically less pure than container-based DI. We judge the
  trade-off worth it given how much simpler the production code stays.
- **Import-order matters.** A circular import between two option
  namespaces would silently leave one of them missing from the
  registry. Mitigated by the startup audit (Epic I) which compares
  the populated registry against a frozen snapshot and fails fast.
- **No introspection-driven wiring.** A container can answer "which
  providers satisfy port X?" by reflection. With dicts, the answer is
  "iterate the dict yourself." We've never needed reflection here; the
  catalogues are small enough to iterate trivially.

### Neutral

- The decision is reversible at modest cost. If we ever need true
  per-request lifecycles inside forge itself (we don't anticipate this
  in any roadmap horizon), wrapping the existing dicts in a container's
  provider API is mechanical.

## References

- `forge/options/_registry.py`, `forge/fragments/_registry.py` — the
  canonical examples.
- Epic I (FRAGMENT_REGISTRY freeze + startup audit) — see CHANGELOG
  entry for the defensive freeze hook on `_FragmentRegistry`.
- ADR-002 (ports-and-adapters) — explains why dishka *is* used inside
  generated projects (where the static-vs-dynamic trade-off flips).
- [dishka documentation](https://dishka.readthedocs.io/) — for contrast
  with what a real DI container looks like and why generated FastAPI
  apps want one.
