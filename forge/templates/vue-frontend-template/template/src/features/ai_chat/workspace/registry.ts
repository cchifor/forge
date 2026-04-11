import { defineAsyncComponent, type Component } from 'vue'

export interface WorkspaceComponentEntry {
  component: Component
  label: string
}

const registry = new Map<string, WorkspaceComponentEntry>()

export function registerWorkspaceComponent(activityType: string, entry: WorkspaceComponentEntry) {
  registry.set(activityType, entry)
}

export function resolveWorkspaceComponent(activityType: string): WorkspaceComponentEntry {
  return registry.get(activityType) || registry.get('fallback')!
}

// Built-in registrations
registerWorkspaceComponent('credential_form', {
  component: defineAsyncComponent(() => import('./CredentialForm.vue')),
  label: 'Credential Form',
})
registerWorkspaceComponent('file_explorer', {
  component: defineAsyncComponent(() => import('./FileExplorer.vue')),
  label: 'File Explorer',
})
registerWorkspaceComponent('approval_review', {
  component: defineAsyncComponent(() => import('./ApprovalReview.vue')),
  label: 'Review & Approve',
})
registerWorkspaceComponent('user_prompt', {
  component: defineAsyncComponent(() => import('./UserPromptReview.vue')),
  label: 'Question',
})
registerWorkspaceComponent('fallback', {
  component: defineAsyncComponent(() => import('./FallbackActivity.vue')),
  label: 'Activity',
})
