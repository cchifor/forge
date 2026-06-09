import { defineAsyncComponent } from 'vue'
import { ComponentRegistry, type ComponentEntry } from '../registry/ComponentRegistry'

export type CanvasComponentEntry = ComponentEntry

const canvasRegistry = new ComponentRegistry()

export function registerCanvasComponent(activityType: string, entry: CanvasComponentEntry) {
  canvasRegistry.register(activityType, entry)
}

export function resolveCanvasComponent(activityType: string): CanvasComponentEntry {
  return canvasRegistry.resolve(activityType)
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
registerCanvasComponent('approval', {
  component: defineAsyncComponent(() => import('./ConfirmTool.vue')),
  label: 'Approval',
})
