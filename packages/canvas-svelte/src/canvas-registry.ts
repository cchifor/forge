// Canvas component registry — Svelte 5 variant.

import type { Component } from 'svelte'

import { lintProps, warnOnLintIssues } from './lint'

export interface CanvasComponent<Props = Record<string, unknown>> {
  name: string
  component: Component
  propsSchema?: Record<string, unknown>
}

export interface CanvasResolution<Props = Record<string, unknown>> {
  entry: CanvasComponent<Props>
  issues: readonly { field: string; message: string }[]
}

export interface CanvasRegistry {
  register(entry: CanvasComponent): void
  resolve(name: string): CanvasComponent | null
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
