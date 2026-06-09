import type { Component } from 'vue'

export interface ComponentEntry {
  component: Component
  label: string
}

/**
 * Generic component registry: maps activity type strings to Vue components.
 * Used by both canvas and workspace panes for resolving AG-UI components.
 */
export class ComponentRegistry {
  private map = new Map<string, ComponentEntry>()

  register(activityType: string, entry: ComponentEntry): void {
    this.map.set(activityType, entry)
  }

  resolve(activityType: string): ComponentEntry {
    return this.map.get(activityType) || this.map.get('fallback')!
  }

  has(activityType: string): boolean {
    return this.map.has(activityType)
  }

  entries(): IterableIterator<[string, ComponentEntry]> {
    return this.map.entries()
  }
}
