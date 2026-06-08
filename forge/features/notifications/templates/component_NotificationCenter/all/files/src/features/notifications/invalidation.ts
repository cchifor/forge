/**
 * Map a notification's ``entity_type`` to TanStack Query keys to invalidate.
 * When an entity's lifecycle notification arrives (e.g. a job finishes), the
 * cached rows for that entity flip stale → the next view re-fetches.
 *
 * The registry is open: a generated app registers the entity types its
 * backend emits, near app bootstrap, so the cache invalidation lines up with
 * its own query keys. If a notification carries no ``entity_type`` (or an
 * unregistered one) no invalidation fires — the toast still surfaces, the user
 * just doesn't see a data refresh.
 *
 * Example (call once per entity, e.g. alongside ``startNotifications``):
 *
 *   registerInvalidation('items', (id) => [
 *     ['items', 'list'],
 *     ...(id ? [['items', 'detail', id]] : []),
 *   ])
 */
import type { QueryClient } from '@tanstack/vue-query'

import type { Notification } from './types'

export type EntityKeyBuilder = (entityId: string | null) => unknown[][]

const REGISTRY: Record<string, EntityKeyBuilder> = {}

/** Register the TanStack Query keys an entity type's notifications invalidate. */
export function registerInvalidation(entityType: string, build: EntityKeyBuilder): void {
  REGISTRY[entityType] = build
}

/** Clear all registrations (used in tests). */
export function clearInvalidationRegistry(): void {
  for (const k of Object.keys(REGISTRY)) delete REGISTRY[k]
}

export function invalidateForNotification(
  queryClient: QueryClient,
  notification: Notification,
): void {
  if (!notification.entity_type) return
  const builder = REGISTRY[notification.entity_type]
  if (!builder) return
  for (const queryKey of builder(notification.entity_id)) {
    queryClient.invalidateQueries({ queryKey })
  }
}
