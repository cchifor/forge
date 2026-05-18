<!--
  CanvasError — error boundary for canvas-rendered components.

  v2 Theme 8-C2 — wraps a downstream subtree and traps any error thrown
  during render or in a child's lifecycle via Vue 3's onErrorCaptured.
  Without this boundary, a single buggy canvas activity cascades into
  the parent app (e.g. <CanvasPane>) and unmounts the whole route.

  On capture, the slot is replaced with a fallback card naming the
  failing component, surfacing the error message, and offering Retry
  (bumps an internal `key` to force a remount of the slot subtree) +
  Report (only rendered when an `onReport` callback prop is provided).

  Mirrors packages/canvas-vue/src/components/CanvasError.vue — kept as
  a template-local sibling so the generated app has no new package
  dependency on @forge/canvas-vue.
-->
<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { AlertCircle } from 'lucide-vue-next'

interface Props {
  componentName?: string
  onReport?: (error: Error, componentName: string | undefined) => void
}

const props = defineProps<Props>()

const hasError = ref(false)
const capturedError = ref<Error | null>(null)
const slotKey = ref(0)

onErrorCaptured((err) => {
  hasError.value = true
  capturedError.value = err instanceof Error ? err : new Error(String(err))
  return false
})

function retry() {
  hasError.value = false
  capturedError.value = null
  slotKey.value += 1
}

function report() {
  if (props.onReport && capturedError.value) {
    props.onReport(capturedError.value, props.componentName)
  }
}
</script>

<template>
  <div
    v-if="hasError"
    class="flex items-start gap-3 rounded-lg border border-destructive/50 bg-destructive/5 p-4"
    role="alert"
  >
    <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-destructive/10">
      <AlertCircle class="h-5 w-5 text-destructive" />
    </div>
    <div class="flex flex-1 flex-col gap-1">
      <p class="text-sm font-medium text-destructive">
        {{ componentName ? `${componentName} failed to render` : 'Canvas component failed to render' }}
      </p>
      <p v-if="capturedError" class="break-words font-mono text-xs text-muted-foreground">
        {{ capturedError.message || 'Unknown error' }}
      </p>
      <div class="mt-2 flex gap-2">
        <button
          type="button"
          class="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          @click="retry"
        >
          Retry
        </button>
        <button
          v-if="props.onReport"
          type="button"
          class="rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent"
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
