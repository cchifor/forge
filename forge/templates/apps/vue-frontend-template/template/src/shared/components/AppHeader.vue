<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { AiChatButton } from '@/features/ai_chat'
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/shared/ui/breadcrumb'

defineProps<{ compact?: boolean }>()

const route = useRoute()

const breadcrumbs = computed(() => {
  const crumbs: { label: string; to?: string }[] = []
  const matched = route.matched.filter((r) => r.meta.title)
  matched.forEach((record, index) => {
    crumbs.push({
      label: record.meta.title as string,
      to: index < matched.length - 1 ? record.path || '/' : undefined,
    })
  })
  return crumbs
})
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-2 border-b px-4">
    <Breadcrumb>
      <BreadcrumbList>
        <template v-for="(crumb, i) in breadcrumbs" :key="i">
          <BreadcrumbItem>
            <BreadcrumbLink v-if="crumb.to" as-child>
              <RouterLink :to="crumb.to">{{ crumb.label }}</RouterLink>
            </BreadcrumbLink>
            <BreadcrumbPage v-else>{{ crumb.label }}</BreadcrumbPage>
          </BreadcrumbItem>
          <BreadcrumbSeparator v-if="i < breadcrumbs.length - 1" />
        </template>
      </BreadcrumbList>
    </Breadcrumb>

    <div class="ml-auto flex items-center gap-2">
      <AiChatButton />
    </div>
  </header>
</template>
