// Canvas component registry — Svelte 5 variant.

import type { Component } from 'svelte'

export interface CanvasComponent<Props = Record<string, unknown>> {
  name: string
  component: Component
  propsSchema?: Record<string, unknown>
}

export interface CanvasRegistry {
  register(entry: CanvasComponent): void
  resolve(name: string): CanvasComponent | null
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
    entries() {
      return Array.from(entries.values())
    },
  }
}
