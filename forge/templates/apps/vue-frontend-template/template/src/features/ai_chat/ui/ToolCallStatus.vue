<script setup lang="ts">
import { computed } from 'vue'
import { Loader2, Check, X, Clock } from 'lucide-vue-next'

const props = defineProps<{
  toolName: string
  status: 'pending' | 'running' | 'completed' | 'error'
  /**
   * Raw delta-stream buffer (TOOL_CALL_ARGS accumulation). Shown
   * inside the ``<details>`` while the call is still running so users
   * see what the tool was invoked with without waiting for the
   * (potentially slow) tool to return.
   */
  argsBuffer?: string
  /**
   * Pretty-printed JSON, set on TOOL_CALL_END. ``JSON.stringify`` with
   * 2-space indent on parse success, raw buffer on parse error. Cross-
   * stack consistent with Svelte + Flutter.
   */
  argsPretty?: string
}>()

// While streaming we show the raw buffer with newlines stripped — the
// model often emits a partial JSON like `{"foo":\n  "bar"` and the
// embedded newlines push the preview taller than it needs to be. On
// END, ``argsPretty`` takes over and we want the indentation back.
const displayArgs = computed(() => {
  if (props.argsPretty !== undefined && props.argsPretty.length > 0) {
    return props.argsPretty
  }
  if (props.argsBuffer !== undefined && props.argsBuffer.length > 0) {
    return props.argsBuffer.replace(/\n+/g, ' ')
  }
  return ''
})
</script>

<template>
  <div class="rounded-md border bg-muted/30 text-xs">
    <div class="flex items-center gap-2 px-2.5 py-1.5">
      <Loader2 v-if="status === 'running'" class="h-3.5 w-3.5 animate-spin text-blue-500" />
      <Check v-else-if="status === 'completed'" class="h-3.5 w-3.5 text-green-500" />
      <X v-else-if="status === 'error'" class="h-3.5 w-3.5 text-red-500" />
      <Clock v-else class="h-3.5 w-3.5 text-muted-foreground" />
      <span class="font-mono text-muted-foreground">{{ toolName }}</span>
      <span
        class="ml-auto text-[10px] uppercase tracking-wider"
        :class="{
          'text-blue-500': status === 'running',
          'text-green-500': status === 'completed',
          'text-red-500': status === 'error',
          'text-muted-foreground': status === 'pending',
        }"
      >
        {{ status }}
      </span>
    </div>
    <!-- Collapsible args preview. Native <details> so it works without
         JS state, matches Svelte (HTML <details>) and Flutter
         (ExpansionTile) UX. Default-closed to avoid bloating the
         message column with the full JSON for every tool call. -->
    <details v-if="displayArgs.length > 0" class="border-t" data-testid="tool-call-args">
      <summary
        class="cursor-pointer px-2.5 py-1 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
      >
        args
      </summary>
      <pre
        class="max-h-48 overflow-auto whitespace-pre-wrap break-all px-2.5 py-1.5 font-mono text-[11px] text-foreground"
        data-testid="tool-call-args-body"
      >{{ displayArgs }}</pre>
    </details>
  </div>
</template>
