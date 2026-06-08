<!--
  Stale-stream pill that surfaces when the SSE connection has been down (or
  reconnecting) for more than a short grace period.

  Broadcast events tick the bell badge via the live stream; if the stream drops
  silently the bell appears frozen. This banner gives an explicit "your views
  may be stale" signal. Reads the connection ref from the notification store;
  ``connecting`` is normal on first boot, so it only surfaces after a 5s grace
  to absorb transient reconnects.
-->
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useNotificationStore } from '../store'

const store = useNotificationStore()

const GRACE_MS = 5_000
const sinceUnhealthy = ref<number | null>(null)
const now = ref(Date.now())

let tick: ReturnType<typeof setInterval> | null = null

// ``store.connection`` is 'connecting' | 'open' | 'closed' | 'error'; healthy is
// 'open'.
const isUnhealthy = computed(() => store.connection !== 'open')

const visible = computed(() => {
  if (!isUnhealthy.value) return false
  if (sinceUnhealthy.value === null) return false
  return now.value - sinceUnhealthy.value >= GRACE_MS
})

const label = computed(() => {
  switch (store.connection) {
    case 'connecting':
      return 'Reconnecting…'
    case 'closed':
    case 'error':
      return 'Live updates unavailable'
    default:
      return 'Reconnecting…'
  }
})

function refresh() {
  now.value = Date.now()
  if (isUnhealthy.value && sinceUnhealthy.value === null) {
    sinceUnhealthy.value = now.value
  } else if (!isUnhealthy.value) {
    sinceUnhealthy.value = null
  }
}

onMounted(() => {
  refresh()
  tick = setInterval(refresh, 1_000)
})

onUnmounted(() => {
  if (tick !== null) clearInterval(tick)
})
</script>

<template>
  <div
    v-if="visible"
    role="status"
    aria-live="polite"
    class="notification-connection-banner"
  >
    {{ label }}
  </div>
</template>

<style scoped>
.notification-connection-banner {
  position: fixed;
  bottom: 4rem;
  right: 1rem;
  z-index: 9998;
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--color-warning-bg, #fef3c7);
  color: var(--color-warning-fg, #92400e);
  border: 1px solid var(--color-warning-border, #fde68a);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}
</style>
