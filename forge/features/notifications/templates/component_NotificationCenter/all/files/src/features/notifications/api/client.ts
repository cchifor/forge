/**
 * REST client for the notification inbox endpoints.
 *
 * Uses the app's shared ``ky`` client so 401/refresh/CSRF handling lines up
 * with every other API call. ``BASE`` is the single place to re-point if your
 * backend exposes notifications under a different prefix.
 *
 * NOTE: these REST endpoints are the "inbox" surface (list / unread-count /
 * mark-read / clear). The live bell is driven by SSE (``api/stream.ts``) and
 * works without them; until a backend implements the inbox, the store tolerates
 * 404s from these calls (it drops the row locally).
 */
import { useQuery, useQueryClient, useMutation } from '@tanstack/vue-query'

import { getApiClient } from '@/shared/api/client'
import { appConfig } from '@/shared/config/runtime'

import type { PaginatedNotifications, UnreadCount } from '../types'

// ky is configured with ``prefixUrl``; the input MUST NOT start with a slash
// and is appended verbatim.
const BASE = 'api/v1/notifications'

export const notificationKeys = {
  all: ['notifications'] as const,
  list: (unread: boolean) => [...notificationKeys.all, 'list', { unread }] as const,
  unreadCount: () => [...notificationKeys.all, 'unread-count'] as const,
}

export function useNotificationsQuery(unread = false) {
  return useQuery({
    queryKey: notificationKeys.list(unread),
    queryFn: () =>
      getApiClient()
        .get(BASE, {
          searchParams: unread ? { unread: 'true' } : {},
        })
        .json<PaginatedNotifications>(),
    staleTime: appConfig.cache.staleTimeDefaultMs,
  })
}

export function useUnreadCountQuery() {
  return useQuery({
    queryKey: notificationKeys.unreadCount(),
    queryFn: () =>
      getApiClient().get(`${BASE}/unread-count`).json<UnreadCount>(),
    staleTime: appConfig.cache.staleTimeDefaultMs,
  })
}

export function useMarkReadMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notificationId: string) =>
      getApiClient().post(`${BASE}/${notificationId}/read`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useMarkAllReadMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => getApiClient().post(`${BASE}/read-all`).json<{ marked: number }>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useDeleteMutation() {
  const qc = useQueryClient()
  return useMutation({
    // ky throws on non-2xx by default; the caller handles 404 ("already gone").
    mutationFn: (notificationId: string) =>
      getApiClient().delete(`${BASE}/${notificationId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useClearAllMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      getApiClient().delete(BASE).json<{ cleared: number }>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}
