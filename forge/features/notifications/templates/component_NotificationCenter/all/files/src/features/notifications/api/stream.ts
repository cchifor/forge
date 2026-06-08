/**
 * SSE stream client for live notifications.
 *
 * Opens one connection to the app's event stream (the generated ``streaming``
 * backend feature mounts ``GET /api/v1/stream`` as ``text/event-stream``),
 * decodes each ``data:`` line, maps it to a :class:`Notification`, and pushes
 * into the Pinia store. ``useEventStream`` owns the Last-Event-ID resume +
 * backoff, so a reconnect picks up where it left off.
 *
 * Wire shape: the backend stream emits **CloudEvents** (`{id,type,time,data}`).
 * ``toNotification`` maps a CloudEvent → the rendered ``Notification`` row the
 * store/UI expect, pulling ``title``/``severity``/``entity_*`` from the event
 * ``data`` when the producer populates them (with sensible fallbacks). If your
 * backend already emits rendered ``Notification`` rows, those pass through
 * unchanged.
 */
import type { QueryClient } from '@tanstack/vue-query'

import { useEventStream } from '@/shared/composables/useEventStream'

import { invalidateForNotification } from '../invalidation'
import type { NotificationStore } from '../store'
import type { Notification, Severity } from '../types'

const STREAM_URL = '/api/v1/stream'

const VALID_SEVERITIES: readonly Severity[] = ['info', 'success', 'warn', 'error']

function asSeverity(v: unknown): Severity {
  return typeof v === 'string' && (VALID_SEVERITIES as readonly string[]).includes(v)
    ? (v as Severity)
    : 'info'
}

/**
 * Map a raw SSE payload to a ``Notification``. Accepts either an
 * already-rendered notification row or a CloudEvent envelope. ``seq`` is a
 * client-assigned monotonic ordinal (arrival order) so the center sorts
 * newest-first even when the transport id isn't numeric.
 */
function toNotification(raw: unknown, seq: number, fallbackId: string): Notification {
  const o = (raw ?? {}) as Record<string, unknown>
  // Already a rendered notification row → pass through (assign seq if absent).
  if (typeof o.event_type === 'string' && typeof o.title === 'string') {
    return { ...(o as unknown as Notification), seq: typeof o.seq === 'number' ? o.seq : seq }
  }
  // CloudEvent envelope.
  const data = (o.data && typeof o.data === 'object' ? (o.data as Record<string, unknown>) : {})
  const id = String(o.id ?? fallbackId)
  return {
    id,
    seq,
    event_id: id,
    event_type: String(o.type ?? 'event'),
    severity: asSeverity(data.severity),
    title: String(data.title ?? o.type ?? 'Notification'),
    body: (data.body as string | null) ?? null,
    deep_link: (data.deep_link as string | null) ?? null,
    entity_type: (data.entity_type as string | null) ?? (o.subject as string | null) ?? null,
    entity_id: (data.entity_id as string | null) ?? null,
    metadata: data.metadata as Notification['metadata'],
    read_at: null,
    created_at: String(o.time ?? new Date().toISOString()),
  }
}

export interface NotificationStreamHandle {
  disconnect: () => void
}

export function openNotificationStream(
  store: NotificationStore,
  queryClient: QueryClient,
): NotificationStreamHandle {
  let seq = 0
  const { connection, disconnect } = useEventStream({
    url: STREAM_URL,
    autoDisconnectOnUnmount: false,
    onMessage(msg) {
      if (!msg.data) return
      let raw: unknown
      try {
        raw = JSON.parse(msg.data)
      } catch {
        return
      }
      seq += 1
      const n = toNotification(raw, seq, msg.id || `evt-${seq}`)
      store.ingest(n)
      invalidateForNotification(queryClient, n)
    },
  })

  // Mirror the connection state into the store so the banner can react.
  const stop = setInterval(() => {
    store.setConnection(connection.value)
  }, 250)

  return {
    disconnect: () => {
      clearInterval(stop)
      disconnect()
    },
  }
}
