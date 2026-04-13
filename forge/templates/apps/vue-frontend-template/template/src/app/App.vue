<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { Toaster } from 'vue-sonner'
import { useAiChat } from '@/features/ai_chat'

const { toggleChat } = useAiChat()

function handleKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
    e.preventDefault()
    toggleChat()
  }
}

onMounted(() => document.addEventListener('keydown', handleKeydown))
onUnmounted(() => document.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <RouterView />
  <Toaster
    position="bottom-right"
    :expand="true"
    rich-colors
    close-button
  />
</template>
