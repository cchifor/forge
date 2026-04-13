<script setup lang="ts">
import { Loader2, Check, X, Clock } from 'lucide-vue-next'

defineProps<{
  toolName: string
  status: 'pending' | 'running' | 'completed' | 'error'
}>()
</script>

<template>
  <div class="flex items-center gap-2 rounded-md border bg-muted/30 px-2.5 py-1.5 text-xs">
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
</template>
