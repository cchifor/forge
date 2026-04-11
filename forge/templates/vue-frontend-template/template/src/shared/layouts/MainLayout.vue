<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Home, Package, User, Settings } from 'lucide-vue-next'
import AppSidebar from '@/shared/components/AppSidebar.vue'
import AppHeader from '@/shared/components/AppHeader.vue'
import VerticalSplitter from '@/shared/components/VerticalSplitter.vue'
import { AiChat, WorkspacePane, CanvasPane } from '@/features/ai_chat'
import { useAiChat, useWorkspace, useCanvas } from '@/features/ai_chat'
import { useBreakpoint } from '@/shared/composables/useBreakpoint'
import { useUiStore } from '@/shared/stores/ui.store'

const route = useRoute()
const router = useRouter()
const { chatOpen, closeChat } = useAiChat()
const workspace = useWorkspace()
const canvas = useCanvas()
const { isCompact, isMedium, isExpanded, width: viewportWidth } = useBreakpoint()
const uiStore = useUiStore()
const isDragging = ref(false)
const showCanvas = computed(() => canvas.hasCanvas.value)
const showWorkspace = computed(() => !showCanvas.value && chatOpen.value && workspace.hasActivity.value)

const sidebarWidth = computed(() => {
  if (isCompact.value) return 0
  if (isMedium.value) return 72
  return uiStore.sidebarCollapsed ? 72 : 240
})

const availableWidth = computed(() => viewportWidth.value - sidebarWidth.value)

const chatPixelWidth = computed(() => {
  if (!chatOpen.value) return 0
  const raw = uiStore.chatWidthRatio * availableWidth.value
  return Math.max(280, Math.min(raw, availableWidth.value - 300))
})

function onDragStart() {
  isDragging.value = true
}

function onDragUpdate(clientX: number) {
  const chatWidth = viewportWidth.value - clientX
  const ratio = chatWidth / availableWidth.value
  uiStore.setChatWidthRatio(ratio)
}

function onDragEnd() {
  isDragging.value = false
  uiStore.commitChatWidthRatio()
}

function onDoubleTap() {
  uiStore.setChatWidthRatio(0.33)
  uiStore.commitChatWidthRatio()
}

// Bottom nav for compact
const bottomNavItems = [
  { title: 'Home', url: '/', icon: Home },
  { title: 'Items', url: '/items', icon: Package },
  { title: 'Profile', url: '/profile', icon: User },
  { title: 'Settings', url: '/settings', icon: Settings },
]

function isNavActive(url: string) {
  if (url === '/') return route.path === '/'
  return route.path.startsWith(url)
}
</script>

<template>
  <!-- ═══ EXPANDED (≥840px) ═══ -->
  <div v-if="isExpanded" class="flex h-svh overflow-hidden">
    <AppSidebar />
    <div
      class="flex flex-1 flex-col overflow-hidden"
      :class="{ 'pointer-events-none select-none': isDragging }"
    >
      <AppHeader />
      <main class="flex-1 overflow-auto p-4">
        <CanvasPane v-if="showCanvas" />
        <WorkspacePane v-else-if="showWorkspace" />
        <RouterView v-else />
      </main>
    </div>
    <template v-if="chatOpen">
      <VerticalSplitter
        @drag-start="onDragStart"
        @drag-update="onDragUpdate"
        @drag-end="onDragEnd"
        @double-tap="onDoubleTap"
      />
      <div
        class="shrink-0 overflow-hidden"
        :style="{ width: chatPixelWidth + 'px' }"
        :class="{ 'pointer-events-none select-none': isDragging }"
      >
        <AiChat />
      </div>
    </template>
  </div>

  <!-- ═══ MEDIUM (600-839px) ═══ -->
  <div v-else-if="isMedium" class="flex h-svh overflow-hidden">
    <AppSidebar :force-collapsed="true" />
    <div class="flex flex-1 flex-col overflow-hidden">
      <AppHeader />
      <main class="flex-1 overflow-auto p-4">
        <RouterView />
      </main>
    </div>
    <Transition name="chat-drawer">
      <div
        v-if="chatOpen"
        class="fixed right-0 top-0 z-40 h-svh w-[360px] border-l bg-background shadow-xl"
      >
        <AiChat />
      </div>
    </Transition>
  </div>

  <!-- ═══ COMPACT (<600px) ═══ -->
  <div v-else class="flex h-svh flex-col overflow-hidden">
    <AppHeader :compact="true" />
    <main class="flex-1 overflow-auto p-4">
      <RouterView />
    </main>

    <!-- Bottom Navigation Bar -->
    <nav class="flex h-14 shrink-0 items-center border-t bg-card">
      <RouterLink
        v-for="item in bottomNavItems"
        :key="item.url"
        :to="item.url"
        class="flex flex-1 flex-col items-center gap-0.5 py-2 text-xs interactive-press"
        :class="isNavActive(item.url) ? 'text-primary' : 'text-muted-foreground'"
      >
        <component :is="item.icon" class="h-5 w-5" />
        <span>{{ item.title }}</span>
      </RouterLink>
    </nav>

    <!-- Chat as modal bottom sheet -->
    <Teleport to="body">
      <Transition name="chat-modal">
        <div
          v-if="chatOpen"
          class="fixed inset-0 z-50 flex flex-col justify-end"
        >
          <div
            class="absolute inset-0 bg-black/50"
            @click="closeChat"
          />
          <div class="relative max-h-[90vh] min-h-[50vh] rounded-t-2xl border-t bg-background shadow-xl">
            <div class="mx-auto my-2 h-1 w-10 rounded-full bg-muted-foreground/30" />
            <AiChat />
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
/* Drawer slide from right */
.chat-drawer-enter-active,
.chat-drawer-leave-active {
  transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1);
}
.chat-drawer-enter-from,
.chat-drawer-leave-to {
  transform: translateX(100%);
}

/* Modal from bottom */
.chat-modal-enter-active,
.chat-modal-leave-active {
  transition: opacity 200ms ease;
}
.chat-modal-enter-active > :last-child,
.chat-modal-leave-active > :last-child {
  transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1);
}
.chat-modal-enter-from,
.chat-modal-leave-to {
  opacity: 0;
}
.chat-modal-enter-from > :last-child,
.chat-modal-leave-to > :last-child {
  transform: translateY(100%);
}

@media (prefers-reduced-motion: reduce) {
  .chat-drawer-enter-active,
  .chat-drawer-leave-active,
  .chat-modal-enter-active,
  .chat-modal-leave-active,
  .chat-modal-enter-active > :last-child,
  .chat-modal-leave-active > :last-child {
    transition-duration: 0ms;
  }
}
</style>
