<script setup lang="ts">
import { computed } from 'vue'
import { Pencil, CheckCircle, Archive } from 'lucide-vue-next'

const props = defineProps<{ status: string }>()

const config = computed(() => {
  switch (props.status) {
    case 'DRAFT':
      return { icon: Pencil, label: 'Draft', color: 'text-orange-600 bg-orange-100 dark:text-orange-400 dark:bg-orange-900/30' }
    case 'ACTIVE':
      return { icon: CheckCircle, label: 'Active', color: 'text-green-600 bg-green-100 dark:text-green-400 dark:bg-green-900/30' }
    case 'ARCHIVED':
      return { icon: Archive, label: 'Archived', color: 'text-gray-600 bg-gray-100 dark:text-gray-400 dark:bg-gray-800/50' }
    default:
      return { icon: Pencil, label: props.status, color: 'text-gray-600 bg-gray-100 dark:text-gray-400 dark:bg-gray-800/50' }
  }
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
    :class="config.color"
  >
    <component :is="config.icon" class="h-3.5 w-3.5" />
    {{ config.label }}
  </span>
</template>
