/**
 * Pinia store for notifications.
 *
 * Single source of truth for the bell badge, the notification center panel, the
 * per-entity activity feed, and the toast queue. Updated by:
 *
 * * The SSE stream (``api/stream.ts``) for live events.
 * * The REST client (``api/client.ts``) for the initial fetch + mark-as-read.
 * * Your own mutation hooks for *optimistic* toasts that pop the moment the
 *   user clicks, then resolve in-place when the matching SSE event arrives.
 *
 * Toast lifecycle:
 *
 *   t=0     user clicks an action
 *           → store.pushOptimistic(...) creates a ``pending`` toast keyed by
 *             (entity_type, entity_id, verb).
 *   t≈200ms SSE ``*.started`` arrives → dedupe against the optimistic toast
 *           (same correlation key) → no second toast.
 *   t≈Ns    SSE ``*.completed/failed/cancelled/succeeded`` arrives → resolve the
 *           optimistic toast in place (state flips, dismiss timer restarts).
 *
 * Audience filter: ``pushToast`` reads ``metadata.actor_id`` from the incoming
 * notification. If it's set and doesn't match the current user's id, the bell
 * badge + activity feed still update but no toast pops — scheduled / other-user
 * actions don't disrupt this user's UI.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import type { StreamConnection as RawStreamConnection } from '@/shared/composables/useEventStream'
import { useAuth } from '@/shared/composables/useAuth'
import { appConfig } from '@/shared/config/runtime'

import type { Notification, Severity } from './types'

const MAX_TOASTS = appConfig.toast.maxConcurrent
/** Cap for the ``event_id`` dedupe set. Count-bounded (LRU on insert),
 *  not time-bounded, so a slow async-persist round-trip can't slip past
 *  the window and pop a second toast for the same logical event. */
const RECENT_EVENT_IDS_MAX = 1_000

export type ToastState = 'pending' | 'success' | 'error' | 'info' | 'warn'

export interface Toast {
  id: string
  /** Empty string for purely optimistic toasts that have not yet
   *  resolved to a server notification. */
  notificationId: string
  /** Which lifecycle phase this toast is currently showing. ``pending``
   *  is used for optimistic in-flight toasts; the other states map to
   *  notification severities. */
  state: ToastState
  severity: Severity
  title: string
  body: string | null
  deep_link: string | null
  /** Stable id derived from (entity_type, entity_id, verb). Two
   *  notifications that share a correlationKey are treated as the same
   *  logical action: a ``.started`` event dedupes against an
   *  optimistic toast; a terminal event REPLACES the optimistic toast
   *  in-place rather than spawning a new one. */
  correlationKey: string
  /** Epoch ms when this toast should auto-dismiss. ``null`` means "no
   *  timer yet" — set when the toast resolves. */
  expiresAt: number | null
}

export const useNotificationStore = defineStore('notifications', () => {
  const items = ref<Notification[]>([])
  const unreadCount = ref<number>(0)
  const lastEventId = ref<string>('')
  const connection = ref<RawStreamConnection>('connecting')
  const toasts = ref<Toast[]>([])
  // ``Set`` preserves insertion order, so eviction-of-oldest is just a
  // ``delete(values().next().value)`` when we cross the cap.
  const recentEventIds = new Set<string>()

  // Sorted view for the notification center: most recent first.
  const sortedItems = computed(() =>
    [...items.value].sort((a, b) => b.seq - a.seq),
  )

  /**
   * Return a reactive computed of every notification belonging to
   * ``(entity_type, entity_id)``, newest first. A per-item activity panel
   * uses this so it ticks the instant an SSE event lands — without a separate
   * REST refetch or its own SSE subscription.
   */
  function itemsForEntity(
    entityType: string,
    entityId: string | null | undefined,
  ) {
    return computed(() =>
      entityId
        ? items.value
            .filter(
              (n) => n.entity_type === entityType && n.entity_id === entityId,
            )
            .sort((a, b) => b.seq - a.seq)
        : [],
    )
  }

  /**
   * Verb extraction for correlation.
   *
   * ``com.example.pipeline.sync.started`` → ``sync``
   * ``com.example.workflow.run.queued`` → ``run``
   * ``com.example.workflow.run.succeeded`` → ``run``
   * ``com.example.integration.config_rotated`` → ``config_rotated``
   *
   * The last segment of the event type is treated as the lifecycle suffix when
   * it matches a known lifecycle verb; otherwise the whole trailing chunk is
   * the "verb" (single-shot events). The correlation key combines this with
   * entity_type + entity_id so the SPA can pair queue→start→complete triples
   * even when the event types differ between them.
   */
  const LIFECYCLE_SUFFIXES = new Set([
    'queued',
    'started',
    'succeeded',
    'completed',
    'failed',
    'cancelled',
    'dispatch_failed',
    'truncated',
  ])

  /** Suffixes that represent a logical "in flight" state — the toast
   *  should not pop again for a correlation key that already has one. */
  const IN_FLIGHT_SUFFIXES = new Set(['queued', 'started'])

  function verbFor(eventType: string): string {
    const parts = eventType.split('.')
    if (parts.length < 2) return eventType
    const last = parts[parts.length - 1]
    if (LIFECYCLE_SUFFIXES.has(last)) {
      return parts[parts.length - 2] ?? last
    }
    return last
  }

  function isTerminalSuffix(eventType: string): boolean {
    const last = eventType.split('.').pop() ?? ''
    return LIFECYCLE_SUFFIXES.has(last) && !IN_FLIGHT_SUFFIXES.has(last)
  }

  function isInFlightSuffix(eventType: string): boolean {
    const last = eventType.split('.').pop() ?? ''
    return IN_FLIGHT_SUFFIXES.has(last)
  }

  function correlationKeyFor(
    entityType: string | null | undefined,
    entityId: string | null | undefined,
    verb: string,
  ): string {
    return `${entityType ?? ''}:${entityId ?? ''}:${verb}`
  }

  function correlationKeyForNotification(n: Notification): string {
    return correlationKeyFor(n.entity_type, n.entity_id, verbFor(n.event_type))
  }

  function severityForTerminal(eventType: string, fallback: Severity): Severity {
    const last = eventType.split('.').pop() ?? ''
    if (last === 'succeeded' || last === 'completed') return 'success'
    if (last === 'failed' || last === 'dispatch_failed') return 'error'
    if (last === 'cancelled') return 'info'
    if (last === 'truncated') return 'warn'
    return fallback
  }

  function rememberEventId(eventId: string): void {
    recentEventIds.add(eventId)
    if (recentEventIds.size > RECENT_EVENT_IDS_MAX) {
      const oldest = recentEventIds.values().next().value
      if (oldest !== undefined) recentEventIds.delete(oldest)
    }
  }

  /**
   * Ingest a server-rendered notification into items/unread/lastEventId and (by
   * default) into the toast surface. ``opts.silent`` suppresses only the toast
   * pop — items, unreadCount, lastEventId, and the event_id dedupe set all
   * still update (used by the bootstrap loop so a refresh hydrates the bell
   * without re-popping a toast for every unread row).
   */
  function ingest(n: Notification, opts?: { silent?: boolean }): void {
    if (recentEventIds.has(n.event_id)) {
      return
    }
    rememberEventId(n.event_id)

    const existingIdx = items.value.findIndex((x) => x.seq === n.seq)
    if (existingIdx >= 0) {
      items.value[existingIdx] = n
    } else {
      items.value = [n, ...items.value]
    }

    if (n.read_at === null) {
      unreadCount.value += 1
      if (!opts?.silent) {
        ingestToastForNotification(n)
      }
    }

    if (n.seq > Number(lastEventId.value || 0)) {
      lastEventId.value = String(n.seq)
    }
  }

  /**
   * Push (or morph) the toast for a server-rendered notification. Shared
   * between the SSE-delivered ``ingest`` path and the HTTP-response
   * ``ingestToastOnly`` path so the lifecycle rules live in one place.
   */
  function ingestToastForNotification(n: Notification): void {
    const key = correlationKeyForNotification(n)
    const existingIdx = toasts.value.findIndex(
      (t) => t.correlationKey === key,
    )
    if (existingIdx >= 0) {
      if (isInFlightSuffix(n.event_type)) {
        return
      }
      if (isTerminalSuffix(n.event_type)) {
        resolveToast(key, {
          state: severityForTerminal(n.event_type, n.severity),
          severity: severityForTerminal(n.event_type, n.severity),
          title: n.title,
          body: n.body,
          notificationId: n.id,
          deep_link: n.deep_link,
        })
        return
      }
    }
    pushToast(n)
  }

  /**
   * Ingest a server-rendered notification carried in an HTTP response. The
   * toast surface updates immediately; the bell badge, unread count, and
   * ``lastEventId`` cursor are left to the SSE delivery so they only tick once
   * per server-side row. The ``event_id`` is recorded so the SSE-delivered
   * duplicate is deduped on arrival.
   */
  function ingestToastOnly(n: Notification): void {
    if (recentEventIds.has(n.event_id)) {
      return
    }
    rememberEventId(n.event_id)
    ingestToastForNotification(n)
  }

  function currentUserId(): string | null {
    // Read lazily so the store doesn't fail to construct if auth isn't
    // initialised yet. When the user hasn't loaded, every actor check returns
    // false → no toast pop, which is the safe default.
    try {
      const { user } = useAuth()
      return user.value?.id ?? null
    } catch {
      return null
    }
  }

  function pushToast(n: Notification): void {
    // Suppress the toast pop for events the current user didn't trigger (e.g.
    // another member's action, or a scheduled one with no actor). The bell
    // badge + activity feed already ticked via the ingest path.
    const actorId = n.metadata?.actor_id ?? null
    if (actorId !== null) {
      const me = currentUserId()
      if (me !== null && actorId !== me) {
        return
      }
    } else if (
      n.metadata?.trigger_type === 'schedule' ||
      n.metadata?.trigger_type === 'system'
    ) {
      return
    }

    const t: Toast = {
      id: `${n.id}-${Date.now()}`,
      notificationId: n.id,
      state: severityForTerminal(n.event_type, n.severity),
      severity: n.severity,
      title: n.title,
      body: n.body,
      deep_link: n.deep_link,
      correlationKey: correlationKeyForNotification(n),
      expiresAt: Date.now() + appConfig.toast.durationSuccessMs,
    }
    toasts.value.push(t)
    if (toasts.value.length > MAX_TOASTS) {
      toasts.value = toasts.value.slice(-MAX_TOASTS)
    }
  }

  /**
   * Push a ``pending`` toast immediately on user click. Returns the toast id so
   * callers can resolve or dismiss it if the mutation fails before the SSE
   * round-trips. The ``correlationKey`` is deterministic so the matching SSE
   * event can find this toast later via :func:`resolveToast`.
   */
  function pushOptimistic(opts: {
    entityType: string
    entityId: string
    verb: string
    title: string
    body?: string | null
    deepLink?: string | null
  }): string {
    const key = correlationKeyFor(opts.entityType, opts.entityId, opts.verb)
    const existingIdx = toasts.value.findIndex(
      (t) => t.correlationKey === key,
    )
    if (existingIdx >= 0 && toasts.value[existingIdx].state !== 'pending') {
      return toasts.value[existingIdx].id
    }
    const id = `optimistic-${key}-${Date.now()}`
    const t: Toast = {
      id,
      notificationId: '',
      state: 'pending',
      severity: 'info',
      title: opts.title,
      body: opts.body ?? null,
      deep_link: opts.deepLink ?? null,
      correlationKey: key,
      expiresAt: null,
    }
    if (existingIdx >= 0) {
      toasts.value = [
        ...toasts.value.slice(0, existingIdx),
        t,
        ...toasts.value.slice(existingIdx + 1),
      ]
    } else {
      toasts.value.push(t)
      if (toasts.value.length > MAX_TOASTS) {
        toasts.value = toasts.value.slice(-MAX_TOASTS)
      }
    }
    return id
  }

  /**
   * Transition the toast for ``correlationKey`` to a terminal state. No-op when
   * no toast matches — keeps callers idempotent.
   */
  function resolveToast(
    correlationKey: string,
    patch: {
      state: ToastState
      severity: Severity
      title: string
      body?: string | null
      notificationId?: string
      deep_link?: string | null
    },
  ): void {
    const idx = toasts.value.findIndex((t) => t.correlationKey === correlationKey)
    if (idx < 0) return
    const existing = toasts.value[idx]
    const expiry =
      patch.state === 'error'
        ? appConfig.toast.durationErrorMs
        : appConfig.toast.durationSuccessMs
    toasts.value[idx] = {
      ...existing,
      state: patch.state,
      severity: patch.severity,
      title: patch.title,
      body: patch.body ?? existing.body,
      deep_link: patch.deep_link ?? existing.deep_link,
      notificationId: patch.notificationId ?? existing.notificationId,
      expiresAt: Date.now() + expiry,
    }
  }

  function dismissToast(toastId: string): void {
    toasts.value = toasts.value.filter((t) => t.id !== toastId)
  }

  function markRead(notificationId: string): void {
    const idx = items.value.findIndex((n) => n.id === notificationId)
    if (idx < 0 || items.value[idx].read_at !== null) return
    items.value[idx] = {
      ...items.value[idx],
      read_at: new Date().toISOString(),
    }
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  }

  function markAllRead(): void {
    const now = new Date().toISOString()
    items.value = items.value.map((n) =>
      n.read_at ? n : { ...n, read_at: now },
    )
    unreadCount.value = 0
  }

  /**
   * Drop a single notification from local state. Used both as the optimistic
   * counterpart of the DELETE mutation AND as the recovery path when
   * ``mark_read`` returns 404 (stale row: the server doesn't know about it any
   * more, so neither should we).
   */
  function deleteOne(notificationId: string): void {
    const idx = items.value.findIndex((n) => n.id === notificationId)
    if (idx < 0) return
    const wasUnread = items.value[idx].read_at === null
    items.value = [
      ...items.value.slice(0, idx),
      ...items.value.slice(idx + 1),
    ]
    if (wasUnread) {
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }

  /**
   * Clear every notification currently in the store. Server-preserved
   * broadcasts re-appear on the next list refetch — deliberate; the bell badge
   * ticks down immediately and the background invalidation reconciles.
   */
  function clearAll(): void {
    items.value = []
    unreadCount.value = 0
  }

  function setConnection(state: RawStreamConnection): void {
    connection.value = state
  }

  function setLastEventId(id: string): void {
    lastEventId.value = id
  }

  function reset(): void {
    items.value = []
    unreadCount.value = 0
    toasts.value = []
    recentEventIds.clear()
    lastEventId.value = ''
  }

  return {
    items,
    sortedItems,
    unreadCount,
    lastEventId,
    connection,
    toasts,
    ingest,
    ingestToastOnly,
    pushToast,
    pushOptimistic,
    resolveToast,
    itemsForEntity,
    dismissToast,
    markRead,
    markAllRead,
    deleteOne,
    clearAll,
    setConnection,
    setLastEventId,
    reset,
  }
})

export type NotificationStore = ReturnType<typeof useNotificationStore>
