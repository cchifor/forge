import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useNotificationStore } from '@/features/notifications/store'
import type { Notification } from '@/features/notifications/types'

function notif(over: Partial<Notification> = {}): Notification {
  return {
    id: 'n1',
    seq: 1,
    event_id: 'e1',
    event_type: 'com.example.item.created',
    severity: 'info',
    title: 'Hello',
    body: null,
    deep_link: null,
    entity_type: 'item',
    entity_id: 'i1',
    read_at: null,
    created_at: new Date().toISOString(),
    ...over,
  }
}

describe('notification store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('ingests, counts unread, and dedupes by event_id', () => {
    const s = useNotificationStore()
    s.ingest(notif())
    expect(s.items.length).toBe(1)
    expect(s.unreadCount).toBe(1)
    s.ingest(notif()) // same event_id → ignored
    expect(s.items.length).toBe(1)
    expect(s.unreadCount).toBe(1)
  })

  it('marks one and all read', () => {
    const s = useNotificationStore()
    s.ingest(notif({ id: 'a', event_id: 'ea', seq: 1 }))
    s.ingest(notif({ id: 'b', event_id: 'eb', seq: 2 }))
    expect(s.unreadCount).toBe(2)
    s.markRead('a')
    expect(s.unreadCount).toBe(1)
    s.markAllRead()
    expect(s.unreadCount).toBe(0)
  })

  it('silent ingest hydrates without popping a toast', () => {
    const s = useNotificationStore()
    s.ingest(notif(), { silent: true })
    expect(s.items.length).toBe(1)
    expect(s.toasts.length).toBe(0)
  })

  it('resolves an optimistic toast in place (no duplicate)', () => {
    const s = useNotificationStore()
    s.pushOptimistic({ entityType: 'item', entityId: 'i1', verb: 'sync', title: 'Syncing…' })
    expect(s.toasts).toHaveLength(1)
    expect(s.toasts[0].state).toBe('pending')
    s.resolveToast('item:i1:sync', { state: 'success', severity: 'success', title: 'Synced' })
    expect(s.toasts).toHaveLength(1)
    expect(s.toasts[0].state).toBe('success')
  })

  it('clearAll empties items and unread', () => {
    const s = useNotificationStore()
    s.ingest(notif())
    s.clearAll()
    expect(s.items.length).toBe(0)
    expect(s.unreadCount).toBe(0)
  })
})
