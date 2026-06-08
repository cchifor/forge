/**
 * Notification wire types.
 *
 * The shape mirrors a server-rendered notification row. When your backend
 * exposes an OpenAPI spec for notifications you can replace these with the
 * generated types; for now they are hand-authored so the feature ships
 * standalone.
 */

export type Severity = 'info' | 'success' | 'warn' | 'error'

/**
 * Producer-set metadata carried through to the SPA. Both fields are optional —
 * older event types don't populate them, and the absence of ``actor_id``
 * (system-triggered) is itself meaningful: the toast pump uses it to decide
 * whether to pop a toast (only the actor who triggered the action sees a toast;
 * everyone else ticks the bell silently).
 *
 * ``trigger_type`` is conventionally ``manual``/``schedule``/``webhook``/
 * ``system``; treat anything else as opaque.
 */
export interface NotificationMetadata {
  actor_id?: string
  trigger_type?: string
}

export interface Notification {
  id: string
  seq: number
  event_id: string
  event_type: string
  severity: Severity
  title: string
  body: string | null
  deep_link: string | null
  entity_type: string | null
  entity_id: string | null
  metadata?: NotificationMetadata
  read_at: string | null
  created_at: string
}

export interface PaginatedNotifications {
  items: Notification[]
  total: number
  next_cursor: number | null
}

export interface UnreadCount {
  count: number
}
