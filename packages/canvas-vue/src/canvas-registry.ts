// Canvas component registry — maps component_name strings (from backend
// payloads) to Vue components.
//
// The registry is typed against the canvas manifest so adding a new
// component name at call-time produces a TS error if the component
// hasn't been registered. Dev-mode: `lintAndResolve` validates props
// against the registered JSON Schema before returning the component.

import type { Component } from 'vue'

import { lintProps, warnOnLintIssues } from './lint'

export interface CanvasComponent<_Props = Record<string, unknown>> {
  name: string
  component: Component
  /** Optional JSON Schema for the props — enables runtime lint in dev. */
  propsSchema?: Record<string, unknown>
}

export interface CanvasResolution<Props = Record<string, unknown>> {
  entry: CanvasComponent<Props>
  /** Lint issues (empty in prod or when propsSchema is absent). */
  issues: readonly { field: string; message: string }[]
}

export interface CanvasRegistry {
  register(entry: CanvasComponent): void
  resolve(name: string): CanvasComponent | null
  /** Resolve + validate props against the component's schema. */
  lintAndResolve(
    name: string,
    props: Record<string, unknown>,
  ): CanvasResolution | null
  entries(): readonly CanvasComponent[]
}

export function createCanvasRegistry(initial: CanvasComponent[] = []): CanvasRegistry {
  const entries = new Map<string, CanvasComponent>()
  for (const e of initial) entries.set(e.name, e)

  return {
    register(entry) {
      if (entries.has(entry.name)) {
        throw new Error(`canvas component "${entry.name}" is already registered`)
      }
      entries.set(entry.name, entry)
    },
    resolve(name) {
      return entries.get(name) ?? null
    },
    lintAndResolve(name, props) {
      const entry = entries.get(name)
      if (!entry) return null
      const issues = lintProps(entry.propsSchema, props)
      warnOnLintIssues(entry.name, issues)
      return { entry, issues }
    },
    entries() {
      return Array.from(entries.values())
    },
  }
}
