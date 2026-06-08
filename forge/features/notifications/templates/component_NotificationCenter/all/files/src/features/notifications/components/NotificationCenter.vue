<!--
  Notification center panel content.

  Rendered inside `<PopoverContent>` (NotificationBell.vue) — owns no positioning
  or surface chrome; the popover primitive provides the themed shell and portals
  to <body>. This component is just the panel's interior layout.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { X } from 'lucide-vue-next'

import RelativeTime from '@/shared/components/RelativeTime.vue'

import {
  useClearAllMutation,
  useDeleteMutation,
  useMarkAllReadMutation,
  useMarkReadMutation,
} from '../api/client'
import { navigateToDeepLink } from '../navigate'
import { useNotificationStore } from '../store'
import { toast } from '../toast'
import type { Severity } from '../types'

const store = useNotificationStore()
const router = useRouter()
const markRead = useMarkReadMutation()
const markAllRead = useMarkAllReadMutation()
const deleteOne = useDeleteMutation()
const clearAll = useClearAllMutation()

// Quick-glance affordance: cap the panel at the most recent rows.
const POPOVER_CAP = 20
const items = computed(() => store.sortedItems.slice(0, POPOVER_CAP))

/**
 * ky throws a typed `HTTPError` on non-2xx; duck-type the status code. Treat 404
 * as "the row is gone server-side" — drop it from the store so the UI matches
 * reality.
 */
function statusOf(err: unknown): number | null {
  const r = (err as { response?: { status?: number } } | null)?.response
  return r?.status ?? null
}

function onClickItem(notificationId: string, deepLink: string | null) {
  // Optimistic local update so the badge ticks down immediately.
  store.markRead(notificationId)
  markRead.mutate(notificationId, {
    onError: (err) => {
      if (statusOf(err) === 404) {
        store.deleteOne(notificationId)
      }
    },
  })
  if (deepLink) {
    const outcome = navigateToDeepLink(router, deepLink)
    if (outcome.result === 'unavailable') {
      toast.message('Linked item is no longer available')
    }
  }
}

function onMarkAll() {
  store.markAllRead()
  markAllRead.mutate()
}

function onDelete(notificationId: string) {
  store.deleteOne(notificationId)
  deleteOne.mutate(notificationId, {
    onError: (err) => {
      if (statusOf(err) === 404) return
    },
  })
}

function onClearAll() {
  store.clearAll()
  clearAll.mutate()
}

function severityBorderClass(severity: Severity): string {
  switch (severity) {
    case 'success':
      return 'border-l-emerald-500'
    case 'info':
      return 'border-l-blue-500'
    case 'warn':
      return 'border-l-amber-500'
    case 'error':
      return 'border-l-red-500'
    default:
      return 'border-l-transparent'
  }
}
</script>

<template>
  <div role="dialog" aria-label="Notifications" class="flex flex-col">
    <header
      class="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-3"
    >
      <h2 class="text-sm font-semibold">Notifications</h2>
      <div class="flex items-center gap-3 text-xs">
        <button
          v-if="store.unreadCount > 0"
          type="button"
          class="rounded text-primary transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="onMarkAll"
        >
          Mark all as read
        </button>
        <button
          v-if="items.length > 0"
          type="button"
          class="rounded text-muted-foreground transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="onClearAll"
        >
          Clear all
        </button>
      </div>
    </header>
    <ul v-if="items.length" class="divide-y divide-border/60">
      <li
        v-for="n in items"
        :key="n.id"
        :class="[
          'group/item relative flex cursor-pointer flex-col gap-0.5 border-l-[3px] pl-4 pr-9 py-3 transition-colors hover:bg-muted/50',
          n.read_at ? 'border-l-transparent' : 'bg-primary/[0.04] font-medium',
          severityBorderClass(n.severity),
        ]"
        @click="onClickItem(n.id, n.deep_link)"
      >
        <div class="text-sm">{{ n.title }}</div>
        <div v-if="n.body" class="text-xs text-muted-foreground">
          {{ n.body }}
        </div>
        <RelativeTime
          :timestamp="n.created_at"
          class="text-[11px] text-muted-foreground/70"
        />
        <button
          type="button"
          class="absolute right-2 top-2 inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/item:opacity-100"
          :aria-label="`Dismiss notification: ${n.title}`"
          @click.stop="onDelete(n.id)"
        >
          <X class="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </li>
    </ul>
    <p
      v-else
      class="px-4 py-8 text-center text-sm text-muted-foreground"
    >
      No notifications yet.
    </p>
  </div>
</template>
