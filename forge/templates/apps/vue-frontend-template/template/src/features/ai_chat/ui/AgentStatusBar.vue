<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { useAgentClient } from '../composables/useAgentClient'

const { isRunning, customState } = useAgentClient()

const costDisplay = computed(() => {
  const cost = customState.value?.cost
  if (!cost) return null
  return `$${cost.run_usd?.toFixed(4) ?? '0.00'}`
})

const contextPct = computed(() => {
  const ctx = customState.value?.context
  if (!ctx) return null
  return Math.round(ctx.usage_pct)
})
</script>

<template>
  <div class="flex items-center gap-3 border-t px-4 py-1.5 text-[11px] text-muted-foreground">
    <!-- Status indicator -->
    <div class="flex items-center gap-1.5">
      <Loader2 v-if="isRunning" class="h-3 w-3 animate-spin text-blue-500" />
      <span
        v-else
        class="inline-block h-2 w-2 rounded-full bg-green-500"
      />
      <span>{{ isRunning ? 'Running' : 'Idle' }}</span>
    </div>

    <!-- Cost -->
    <span v-if="costDisplay" class="text-muted-foreground/70">
      Cost: {{ costDisplay }}
    </span>

    <!-- Context usage -->
    <span v-if="contextPct !== null" class="text-muted-foreground/70">
      Context: {{ contextPct }}%
    </span>
  </div>
</template>
