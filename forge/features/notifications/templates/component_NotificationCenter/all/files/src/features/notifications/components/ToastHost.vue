<!--
  Top-level transient toast surface.

  Reads ``store.toasts`` and renders one panel per item. Pending (optimistic)
  toasts stay until resolved by the matching SSE event; resolved toasts
  auto-dismiss when ``expiresAt`` elapses. Hovering pauses the dismiss timer.
  Click navigates to ``deep_link`` when present. This is the single toast
  renderer — if you adopt it, remove vue-sonner's <Toaster/> from App.vue.
-->
<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import { useNotificationStore } from '../store'
import type { Toast } from '../store'

const store = useNotificationStore()
const router = useRouter()

// Per-toast remaining-duration tracking so hover pauses (rather than restarts)
// the auto-dismiss timer.
const timers = new Map<string, ReturnType<typeof setTimeout>>()
const pausedIds = new Set<string>()
const remainingMs = new Map<string, number>()

function scheduleDismiss(t: Toast) {
  // Pending toasts never auto-dismiss — they wait for the terminal SSE event.
  if (t.state === 'pending' || t.expiresAt === null) return
  const existing = timers.get(t.id)
  if (existing) {
    clearTimeout(existing)
  }
  if (pausedIds.has(t.id)) return
  const stored = remainingMs.get(t.id)
  const remaining = stored ?? Math.max(0, t.expiresAt - Date.now())
  const handle = setTimeout(() => {
    timers.delete(t.id)
    remainingMs.delete(t.id)
    store.dismissToast(t.id)
  }, remaining)
  timers.set(t.id, handle)
}

function pauseDismiss(t: Toast) {
  if (t.state === 'pending' || t.expiresAt === null) return
  const handle = timers.get(t.id)
  if (handle) {
    clearTimeout(handle)
    timers.delete(t.id)
  }
  pausedIds.add(t.id)
  remainingMs.set(t.id, Math.max(0, t.expiresAt - Date.now()))
}

function resumeDismiss(t: Toast) {
  if (!pausedIds.has(t.id)) return
  pausedIds.delete(t.id)
  const stored = remainingMs.get(t.id)
  if (stored !== undefined) {
    t.expiresAt = Date.now() + stored
  }
  remainingMs.delete(t.id)
  scheduleDismiss(t)
}

function onClick(t: Toast) {
  store.dismissToast(t.id)
  if (t.notificationId) {
    store.markRead(t.notificationId)
  }
  if (t.deep_link) {
    router.push(t.deep_link).catch(() => {
      /* in-page hash links etc. — fall back to noop */
    })
  }
}

function rescheduleAll() {
  for (const t of store.toasts) {
    scheduleDismiss(t)
  }
}

onMounted(rescheduleAll)
watch(
  () => store.toasts.map((t) => `${t.id}:${t.state}:${t.expiresAt}`).join('|'),
  rescheduleAll,
)
onUnmounted(() => {
  for (const handle of timers.values()) {
    clearTimeout(handle)
  }
  timers.clear()
  pausedIds.clear()
  remainingMs.clear()
})

function toastClass(t: Toast): string {
  if (t.state === 'pending') return 'toast toast--pending'
  return `toast toast--${t.state}`
}

const visibleToasts = computed(() => store.toasts)
</script>

<template>
  <div class="toast-host" role="status" aria-live="polite" data-testid="toast-host">
    <div
      v-for="t in visibleToasts"
      :key="t.id"
      :class="toastClass(t)"
      data-testid="toast"
      :data-toast-state="t.state"
      :data-correlation-key="t.correlationKey"
      @click="onClick(t)"
      @mouseenter="pauseDismiss(t)"
      @mouseleave="resumeDismiss(t)"
      @focusin="pauseDismiss(t)"
      @focusout="resumeDismiss(t)"
    >
      <span v-if="t.state === 'pending'" class="toast__spinner" aria-hidden="true" />
      <div class="toast__content">
        <div class="toast__title" data-testid="toast-title">{{ t.title }}</div>
        <div v-if="t.body" class="toast__body">{{ t.body }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 9999;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  cursor: pointer;
  min-width: 280px;
  max-width: 380px;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  background: var(--color-surface, #1f2937);
  color: var(--color-text, #f9fafb);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
  border-left: 4px solid var(--toast-accent, #6b7280);
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  transition: border-left-color 200ms ease;
}

.toast--info { --toast-accent: #3b82f6; }
.toast--success { --toast-accent: #10b981; }
.toast--warn { --toast-accent: #f59e0b; }
.toast--error { --toast-accent: #ef4444; }
.toast--pending { --toast-accent: #6b7280; }

.toast__spinner {
  width: 0.875rem;
  height: 0.875rem;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: toast-spin 0.8s linear infinite;
  margin-top: 0.125rem;
  flex-shrink: 0;
  opacity: 0.7;
}

@keyframes toast-spin {
  to { transform: rotate(360deg); }
}

.toast__content {
  flex: 1 1 auto;
  min-width: 0;
}

.toast__title {
  font-weight: 600;
  font-size: 0.875rem;
}

.toast__body {
  font-size: 0.8125rem;
  margin-top: 0.25rem;
  opacity: 0.85;
}
</style>
