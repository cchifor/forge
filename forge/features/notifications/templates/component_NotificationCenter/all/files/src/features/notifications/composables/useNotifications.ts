/**
 * Singleton entrypoint for the notification feature.
 *
 * First call opens the SSE stream and bootstraps the Pinia store from the
 * recent-list + unread-count REST endpoints (best-effort — if your backend
 * doesn't implement the inbox yet, the bell still hydrates from SSE). Subsequent
 * calls share the same connection (ref-counted; the last release tears it down).
 *
 * Initialise once after auth bootstrap in ``app/main.ts``; the components (bell,
 * center, ToastHost) read straight from :func:`useNotificationStore`.
 *
 * The caller passes ``queryClient`` explicitly because ``startNotifications``
 * runs outside any Vue component setup() context — Vue-Query's
 * ``useQueryClient()`` hook requires injection context and would throw here.
 */
import type { QueryClient } from '@tanstack/vue-query'

import { getApiClient } from '@/shared/api/client'

import type { NotificationStreamHandle } from '../api/stream'
import { openNotificationStream } from '../api/stream'
import { useNotificationStore } from '../store'
import type { PaginatedNotifications, UnreadCount } from '../types'

const BASE = 'api/v1/notifications'

let handle: NotificationStreamHandle | null = null
let refCount = 0

export interface UseNotificationsResult {
  release: () => void
}

export async function startNotifications(
  queryClient: QueryClient,
): Promise<UseNotificationsResult> {
  const store = useNotificationStore()

  refCount += 1
  const release = () => {
    refCount = Math.max(0, refCount - 1)
    if (refCount === 0 && handle) {
      handle.disconnect()
      handle = null
    }
  }

  if (handle !== null) {
    return { release }
  }

  // Bootstrap: hydrate the store with what the server already has. The SSE
  // replay phase covers anything after connect; the bootstrap covers everything
  // before. Best-effort — a missing inbox backend just leaves the bell to
  // hydrate from the live stream.
  try {
    const client = getApiClient()
    const [list, unread] = await Promise.all([
      client.get(BASE, { searchParams: { limit: '50' } }).json<PaginatedNotifications>(),
      client.get(`${BASE}/unread-count`).json<UnreadCount>(),
    ])
    for (const item of list.items.slice().reverse()) {
      // ``silent`` keeps hydration but skips the toast pop so a refresh doesn't
      // re-toast every unread row.
      store.ingest(item, { silent: true })
    }
    if (list.items.length > 0) {
      // Seed the SSE resume cursor with the *transport* id of the newest known
      // row (``event_id``), so the stream's initial connect asks the server to
      // replay only what we missed. (``seq`` is a client sort ordinal, not a
      // transport cursor — see store.ts.) Requires the backend to honour
      // Last-Event-ID; harmless otherwise.
      const newest = list.items.reduce((acc, item) => (item.seq > acc.seq ? item : acc))
      if (newest.event_id) store.setLastEventId(newest.event_id)
    }
    if (typeof unread.count === 'number') {
      store.unreadCount = unread.count
    }
  } catch (err) {
    console.warn('notification bootstrap failed; continuing with stream only', err)
  }

  handle = openNotificationStream(store, queryClient)
  return { release }
}
