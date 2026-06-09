<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { formatAbsolute, formatRelative } from '@/shared/lib/formatTime'

const props = withDefaults(
  defineProps<{
    timestamp: string | null
    fallback?: string
  }>(),
  { fallback: '—' },
)

// Keep the relative label fresh: a 60s tick while visible, plus a
// visibilitychange resync so a tab backgrounded for an hour doesn't display
// "1m ago" until the next minute tick.
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

function handleVisibilityChange() {
  if (typeof document === 'undefined') return
  if (document.visibilityState === 'visible') {
    now.value = Date.now()
  }
}

onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now()
  }, 60_000)
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
  }
})
</script>

<template>
  <span :title="formatAbsolute(props.timestamp)">
    {{ props.timestamp ? formatRelative(props.timestamp, now) : props.fallback }}
  </span>
</template>
