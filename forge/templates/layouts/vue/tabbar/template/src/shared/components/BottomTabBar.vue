<script setup lang="ts">
import type { Component } from 'vue'
import { useRoute } from 'vue-router'

export interface TabItem {
  title: string
  url: string
  icon: Component
}

defineProps<{ items: TabItem[] }>()

const route = useRoute()

function isNavActive(url: string) {
  if (url === '/') return route.path === '/'
  return route.path.startsWith(url)
}
</script>

<template>
  <nav
    class="flex h-14 shrink-0 items-center border-t bg-card"
    aria-label="Primary navigation"
  >
    <RouterLink
      v-for="item in items"
      :key="item.url"
      :to="item.url"
      :title="item.title"
      :aria-current="isNavActive(item.url) ? 'page' : undefined"
      class="flex flex-1 flex-col items-center gap-0.5 py-2 text-xs interactive-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      :class="isNavActive(item.url) ? 'text-primary' : 'text-muted-foreground hover:text-foreground'"
    >
      <component :is="item.icon" class="h-5 w-5" />
      <span class="w-full truncate text-center">{{ item.title }}</span>
    </RouterLink>
  </nav>
</template>
