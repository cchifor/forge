<script setup lang="ts">
import { PopoverContent, PopoverPortal } from 'radix-vue'
import type { HTMLAttributes } from 'vue'

withDefaults(
  defineProps<{
    class?: HTMLAttributes['class']
    align?: 'start' | 'center' | 'end'
    sideOffset?: number
  }>(),
  { align: 'center', sideOffset: 4 },
)
</script>

<template>
  <PopoverPortal>
    <PopoverContent
      :align="align"
      :side-offset="sideOffset"
      :class="[
        'z-50 rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-none',
        $props.class,
      ]"
    >
      <slot />
    </PopoverContent>
  </PopoverPortal>
</template>
