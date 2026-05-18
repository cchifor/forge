<!--
  CanvasError — error boundary for canvas-rendered components.

  v2 Theme 8-C2 — wraps a downstream subtree and traps any error thrown
  during render or in a child's lifecycle via Vue 3's onErrorCaptured.
  Without this boundary, a single buggy canvas activity cascades into
  the parent app (e.g. <CanvasPane>) and unmounts the whole route.

  On capture, the slot is replaced with a fallback card that names the
  failing component, surfaces the error message, and offers two
  affordances:

    * Retry — bumps an internal `key` so the slot subtree is forced to
      remount. Vue's standard pattern for boundary recovery.
    * Report — only rendered when an `onReport` callback prop is wired
      up; invoked with the captured error + componentName so generated
      apps can plumb it into their telemetry sink of choice.

  Returning `false` from onErrorCaptured stops the error from
  propagating further up the tree.

  TODO: port to svelte/dart canvas packages once the Vue shape settles.
-->
<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'

interface Props {
  /** Human-readable name of the wrapped component, surfaced in the fallback. */
  componentName?: string
  /** Optional reporter callback. When set, a "Report" button is rendered. */
  onReport?: (error: Error, componentName: string | undefined) => void
}

const props = defineProps<Props>()

const hasError = ref(false)
const capturedError = ref<Error | null>(null)
const slotKey = ref(0)

onErrorCaptured((err) => {
  hasError.value = true
  capturedError.value = err instanceof Error ? err : new Error(String(err))
  // Returning false halts further propagation — the parent app stays alive.
  return false
})

function retry() {
  hasError.value = false
  capturedError.value = null
  // Bump the key so the slot's subtree is fully remounted. If the child
  // crashes again, onErrorCaptured fires again and we land back here.
  slotKey.value += 1
}

function report() {
  if (props.onReport && capturedError.value) {
    props.onReport(capturedError.value, props.componentName)
  }
}
</script>

<template>
  <div v-if="hasError" class="forge-canvas-error" role="alert">
    <div class="forge-canvas-error__icon" aria-hidden="true">!</div>
    <div class="forge-canvas-error__body">
      <p class="forge-canvas-error__title">
        {{ componentName ? `${componentName} failed to render` : 'Canvas component failed to render' }}
      </p>
      <p v-if="capturedError" class="forge-canvas-error__message">
        {{ capturedError.message || 'Unknown error' }}
      </p>
      <div class="forge-canvas-error__actions">
        <button type="button" class="forge-canvas-error__retry" @click="retry">
          Retry
        </button>
        <button
          v-if="props.onReport"
          type="button"
          class="forge-canvas-error__report"
          @click="report"
        >
          Report
        </button>
      </div>
    </div>
  </div>
  <template v-else>
    <slot :key="slotKey" />
  </template>
</template>

<style scoped>
.forge-canvas-error { display: flex; gap: 0.75rem; padding: 1rem 1.25rem; background: var(--fc-destructive-bg, #fef2f2); border: 1px solid var(--fc-destructive, #dc2626); border-radius: 0.5rem; align-items: flex-start; }
.forge-canvas-error__icon { flex: 0 0 1.5rem; width: 1.5rem; height: 1.5rem; border-radius: 50%; background: var(--fc-destructive, #dc2626); color: white; font-weight: 700; display: flex; align-items: center; justify-content: center; font-size: 0.875rem; }
.forge-canvas-error__body { flex: 1; display: flex; flex-direction: column; gap: 0.25rem; }
.forge-canvas-error__title { margin: 0; font-weight: 600; font-size: 0.9375rem; color: var(--fc-destructive, #dc2626); }
.forge-canvas-error__message { margin: 0; font-size: 0.8125rem; color: var(--fc-muted-fg, #6b7280); font-family: ui-monospace, monospace; }
.forge-canvas-error__actions { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
.forge-canvas-error__retry { background: var(--fc-primary, #2563eb); color: white; padding: 0.375rem 0.75rem; border: none; border-radius: 0.375rem; cursor: pointer; font-size: 0.8125rem; }
.forge-canvas-error__report { background: transparent; padding: 0.375rem 0.75rem; border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.375rem; cursor: pointer; font-size: 0.8125rem; }
</style>
