# Shared UI Components

Components in this directory are **reusable, domain-agnostic building blocks**. They must remain "dumb":

## Rules

1. Receive all data via `$props()` -- no global state access
2. No imports from `@tanstack/svelte-query` -- no server state coupling
3. No imports from `$lib/features/*` -- no business domain knowledge
4. No imports from `$lib/core/auth` or any store modules
5. Communicate outward via callback props or `$bindable()` -- no side effects

## Allowed Imports

- `$lib/shared/lib/utils` (cn utility)
- `lucide-svelte` (icons)
- `bits-ui` (headless primitives)
- `svelte` (lifecycle, runes)

## Adding Components

Each shared component should have a corresponding `.stories.ts` file for Storybook documentation.
