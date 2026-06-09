import { defineAsyncComponent } from 'vue'
import { ComponentRegistry, type ComponentEntry } from '../registry/ComponentRegistry'

export type WorkspaceComponentEntry = ComponentEntry

const workspaceRegistry = new ComponentRegistry()

export function registerWorkspaceComponent(activityType: string, entry: WorkspaceComponentEntry) {
  workspaceRegistry.register(activityType, entry)
}

export function resolveWorkspaceComponent(activityType: string): WorkspaceComponentEntry {
  return workspaceRegistry.resolve(activityType)
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
