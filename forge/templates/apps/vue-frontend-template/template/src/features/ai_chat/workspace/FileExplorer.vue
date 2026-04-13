<script setup lang="ts">
import { computed } from 'vue'
import { File, FileText, FileCode, Image, Film, Music } from 'lucide-vue-next'
import type { WorkspaceActivity, AgentState, WorkspaceAction } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: WorkspaceAction]
}>()

interface FileEntry {
  path: string
  name: string
  size?: number
  type?: string
}

const files = computed<FileEntry[]>(() => {
  if (Array.isArray(props.activity.content.files)) {
    return props.activity.content.files
  }
  if (props.state?.files && Array.isArray(props.state.files)) {
    return props.state.files
  }
  return []
})

const iconMap: Record<string, any> = {
  image: Image,
  video: Film,
  audio: Music,
  code: FileCode,
  text: FileText,
}

function getIcon(file: FileEntry) {
  if (file.type && iconMap[file.type]) return iconMap[file.type]
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return Image
  if (['mp4', 'mov', 'avi', 'webm'].includes(ext)) return Film
  if (['mp3', 'wav', 'ogg', 'flac'].includes(ext)) return Music
  if (['ts', 'js', 'vue', 'py', 'rs', 'go', 'json', 'yaml', 'toml'].includes(ext)) return FileCode
  if (['txt', 'md', 'csv'].includes(ext)) return FileText
  return File
}

function formatSize(bytes?: number): string {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function selectFile(file: FileEntry) {
  emit('action', {
    type: 'select_file',
    data: { path: file.path },
  })
}
</script>

<template>
  <div class="flex flex-col gap-1 p-4">
    <p v-if="activity.content.description" class="mb-3 text-sm text-muted-foreground">
      {{ activity.content.description }}
    </p>

    <div v-if="files.length === 0" class="py-8 text-center text-sm text-muted-foreground">
      No files available.
    </div>

    <button
      v-for="file in files"
      :key="file.path"
      class="flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted"
      @click="selectFile(file)"
    >
      <component :is="getIcon(file)" class="h-4 w-4 shrink-0 text-muted-foreground" />
      <span class="flex-1 truncate text-sm">{{ file.name }}</span>
      <span v-if="file.size != null" class="shrink-0 text-xs text-muted-foreground">
        {{ formatSize(file.size) }}
      </span>
    </button>
  </div>
</template>
