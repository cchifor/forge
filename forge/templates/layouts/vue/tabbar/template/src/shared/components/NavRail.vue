<script setup lang="ts">
import type { Component } from 'vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Sparkles,
  User,
  SlidersHorizontal,
  LogOut,
} from 'lucide-vue-next'
import { Avatar, AvatarFallback } from '@/shared/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '@/shared/ui/dropdown-menu'
import { useAuth } from '@/shared/composables/useAuth'

export interface RailItem {
  title: string
  url: string
  icon: Component
}

defineProps<{ items: RailItem[] }>()

const route = useRoute()
const router = useRouter()
const { user, logout } = useAuth()

function isActive(url: string) {
  if (url === '/') return route.path === '/'
  return route.path.startsWith(url)
}

const userInitials = computed(() => {
  if (!user.value) return '?'
  return (
    (user.value.firstName?.[0] ?? '') + (user.value.lastName?.[0] ?? '')
  ).toUpperCase() || user.value.username[0]?.toUpperCase() || '?'
})
</script>

<template>
  <aside
    class="flex h-svh w-[72px] shrink-0 flex-col items-center border-r bg-sidebar-background"
  >
    <!-- Brand mark -->
    <div class="shrink-0 px-2 pt-2">
      <div class="flex h-10 w-14 items-center justify-center">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg ai-gradient">
          <Sparkles class="h-4 w-4 text-white" />
        </div>
      </div>
    </div>

    <!-- Icon-only primary nav -->
    <nav
      class="flex flex-1 flex-col gap-1 overflow-y-auto px-2 pt-2"
      aria-label="Primary navigation"
    >
      <RouterLink
        v-for="item in items"
        :key="item.url"
        :to="item.url"
        :title="item.title"
        :aria-current="isActive(item.url) ? 'page' : undefined"
        class="group relative flex h-10 w-14 items-center justify-center rounded-xl interactive-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
        :class="isActive(item.url) ? 'bg-primary/10' : 'hover:bg-sidebar-accent'"
      >
        <div
          v-if="isActive(item.url)"
          class="absolute left-0 h-5 w-[3px] rounded-full bg-primary"
        />
        <component
          :is="item.icon"
          class="h-5 w-5"
          :class="isActive(item.url) ? 'text-primary' : 'text-muted-foreground group-hover:text-sidebar-foreground'"
        />
      </RouterLink>
    </nav>

    <!-- User avatar menu at bottom -->
    <div class="shrink-0 border-t border-sidebar-border px-2 py-2">
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <button
            class="flex h-12 w-14 items-center justify-center rounded-xl hover:bg-sidebar-accent interactive-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
            title="Account"
            aria-label="Account menu"
          >
            <Avatar class="h-8 w-8">
              <AvatarFallback class="text-xs">{{ userInitials }}</AvatarFallback>
            </Avatar>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="end" class="w-56">
          <DropdownMenuLabel>My Account</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem @click="router.push('/profile')">
            <User class="mr-2 h-4 w-4" />
            Account Settings
          </DropdownMenuItem>
          <DropdownMenuItem @click="router.push('/settings')">
            <SlidersHorizontal class="mr-2 h-4 w-4" />
            Preferences
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem @click="logout">
            <LogOut class="mr-2 h-4 w-4" />
            Log Out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </aside>
</template>
