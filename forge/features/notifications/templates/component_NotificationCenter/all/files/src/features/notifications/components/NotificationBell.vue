<!--
  Header bell with unread-count badge.

  Built on the shared `<Popover>` primitive (Radix-based, portals to <body>) so
  it escapes the header's stacking context. Theme tokens (`bg-popover`,
  `bg-destructive`, `text-foreground`, ...) render correctly in light/dark.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { Bell } from 'lucide-vue-next'

import { Popover, PopoverContent, PopoverTrigger } from '@/shared/ui/popover'
import { useNotificationStore } from '../store'
import NotificationCenter from './NotificationCenter.vue'

const store = useNotificationStore()

const display = computed(() => {
  const n = store.unreadCount
  if (n === 0) return ''
  if (n > 99) return '99+'
  return String(n)
})
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <button
        type="button"
        class="relative inline-flex h-9 w-9 items-center justify-center rounded-full text-foreground/80 transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-label="`Notifications${display ? ` (${display} unread)` : ''}`"
      >
        <Bell :size="20" aria-hidden="true" />
        <span
          v-if="display"
          class="absolute right-1 top-1 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-destructive-foreground"
        >
          {{ display }}
        </span>
      </button>
    </PopoverTrigger>
    <PopoverContent
      align="end"
      :side-offset="8"
      class="w-[360px] max-h-[480px] overflow-y-auto p-0"
    >
      <NotificationCenter />
    </PopoverContent>
  </Popover>
</template>
