import { defineAsyncComponent, type Component } from 'vue'

export interface CanvasComponentEntry {
  component: Component
  label: string
}

const registry = new Map<string, CanvasComponentEntry>()

export function registerCanvasComponent(activityType: string, entry: CanvasComponentEntry) {
  registry.set(activityType, entry)
}

export function resolveCanvasComponent(activityType: string): CanvasComponentEntry {
  return registry.get(activityType) || registry.get('fallback')!
}

// Built-in registrations
registerCanvasComponent('fallback', {
  component: defineAsyncComponent(() => import('./CanvasFallback.vue')),
  label: 'Activity',
})
registerCanvasComponent('dynamic_form', {
  component: defineAsyncComponent(() => import('./DynamicForm.vue')),
  label: 'Form',
})
registerCanvasComponent('data_table', {
  component: defineAsyncComponent(() => import('./DataTable.vue')),
  label: 'Data Table',
})
registerCanvasComponent('report', {
  component: defineAsyncComponent(() => import('./Report.vue')),
  label: 'Report',
})
registerCanvasComponent('workflow', {
  component: defineAsyncComponent(() => import('./WorkflowDiagram.vue')),
  label: 'Workflow',
})
registerCanvasComponent('code_viewer', {
  component: defineAsyncComponent(() => import('./CodeViewer.vue')),
  label: 'Code',
})
