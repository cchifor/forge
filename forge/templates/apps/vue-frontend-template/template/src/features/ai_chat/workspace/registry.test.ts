import { describe, it, expect, vi } from 'vitest'
import { defineAsyncComponent } from 'vue'

// Mock Vue async components so imports don't actually resolve .vue files
vi.mock('./CredentialForm.vue', () => ({ default: { name: 'CredentialForm' } }))
vi.mock('./FileExplorer.vue', () => ({ default: { name: 'FileExplorer' } }))
vi.mock('./ApprovalReview.vue', () => ({ default: { name: 'ApprovalReview' } }))
vi.mock('./FallbackActivity.vue', () => ({ default: { name: 'FallbackActivity' } }))

import {
  resolveWorkspaceComponent,
  registerWorkspaceComponent,
  type WorkspaceComponentEntry,
} from './registry'

describe('workspace registry', () => {
  it('resolveWorkspaceComponent credential_form returns entry with label', () => {
    const entry = resolveWorkspaceComponent('credential_form')

    expect(entry).toBeDefined()
    expect(entry.label).toBe('Credential Form')
    expect(entry.component).toBeDefined()
  })

  it('resolveWorkspaceComponent approval_review returns entry with label', () => {
    const entry = resolveWorkspaceComponent('approval_review')

    expect(entry).toBeDefined()
    expect(entry.label).toBe('Review & Approve')
    expect(entry.component).toBeDefined()
  })

  it('resolveWorkspaceComponent unknown_type returns fallback entry', () => {
    const entry = resolveWorkspaceComponent('unknown_type')

    expect(entry).toBeDefined()
    expect(entry.label).toBe('Activity')
    expect(entry.component).toBeDefined()
  })

  it('registerWorkspaceComponent adds custom entry', () => {
    const customEntry: WorkspaceComponentEntry = {
      component: defineAsyncComponent(() => Promise.resolve({ default: { name: 'Custom' } })),
      label: 'Custom Panel',
    }

    registerWorkspaceComponent('custom_panel', customEntry)

    const resolved = resolveWorkspaceComponent('custom_panel')
    expect(resolved).toBeDefined()
    expect(resolved.label).toBe('Custom Panel')
  })

  it('resolveWorkspaceComponent for custom type returns it', () => {
    const customEntry: WorkspaceComponentEntry = {
      component: defineAsyncComponent(() => Promise.resolve({ default: { name: 'Another' } })),
      label: 'Another Custom',
    }

    registerWorkspaceComponent('another_custom', customEntry)

    const resolved = resolveWorkspaceComponent('another_custom')
    expect(resolved.label).toBe('Another Custom')
    expect(resolved.component).toBe(customEntry.component)
  })

  it('all built-in entries have both component and label', () => {
    const builtInTypes = ['credential_form', 'file_explorer', 'approval_review', 'fallback']

    for (const type of builtInTypes) {
      const entry = resolveWorkspaceComponent(type)
      expect(entry.component).toBeDefined()
      expect(typeof entry.label).toBe('string')
      expect(entry.label.length).toBeGreaterThan(0)
    }
  })
})
