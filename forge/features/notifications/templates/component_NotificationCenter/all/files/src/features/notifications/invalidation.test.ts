import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearInvalidationRegistry,
  invalidateForNotification,
  registerInvalidation,
} from '@/features/notifications/invalidation'
import type { Notification } from '@/features/notifications/types'

const qc = { invalidateQueries: vi.fn() } as unknown as import('@tanstack/vue-query').QueryClient

function notif(over: Partial<Notification>): Notification {
  return {
    id: 'n',
    seq: 1,
    event_id: 'e',
    event_type: 't',
    severity: 'info',
    title: '',
    body: null,
    deep_link: null,
    entity_type: null,
    entity_id: null,
    read_at: null,
    created_at: '',
    ...over,
  }
}

describe('invalidation registry', () => {
  beforeEach(() => {
    clearInvalidationRegistry()
    ;(qc.invalidateQueries as ReturnType<typeof vi.fn>).mockClear()
  })

  it('invalidates the registered entity query keys', () => {
    registerInvalidation('items', (id) => [
      ['items', 'list'],
      ...(id ? [['items', 'detail', id]] : []),
    ])
    invalidateForNotification(qc, notif({ entity_type: 'items', entity_id: 'i1' }))
    expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['items', 'list'] })
    expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['items', 'detail', 'i1'] })
  })

  it('no-ops for an unregistered or missing entity_type', () => {
    invalidateForNotification(qc, notif({ entity_type: 'unknown', entity_id: 'x' }))
    invalidateForNotification(qc, notif({ entity_type: null }))
    expect(qc.invalidateQueries).not.toHaveBeenCalled()
  })
})
