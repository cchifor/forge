<script setup lang="ts">
import { computed, ref } from 'vue'
import { Copy, Check, FileCode, GitCompare } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import type { WorkspaceActivity, AgentState } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const schema = computed(() => props.activity.content.props || props.activity.content)
const code = computed(() => schema.value.code || '')
const diff = computed(() => schema.value.diff || null)
const language = computed(() => schema.value.language || 'text')
const title = computed(() => schema.value.title || 'Code')

const activeTab = ref<'code' | 'diff'>(diff.value ? 'diff' : 'code')
const copied = ref(false)

const codeLines = computed(() => code.value.split('\n'))

// Build unified diff display from hunks
const diffLines = computed(() => {
  if (!diff.value?.hunks) return []
  const lines: Array<{ type: 'context' | 'added' | 'removed' | 'header'; text: string; lineNum?: string }> = []
  for (const hunk of diff.value.hunks) {
    lines.push({
      type: 'header',
      text: `@@ -${hunk.old_start},${hunk.old_lines?.length || 0} +${hunk.new_start},${hunk.new_lines?.length || 0} @@`,
    })
    for (const line of hunk.old_lines || []) {
      if (!(hunk.new_lines || []).includes(line)) {
        lines.push({ type: 'removed', text: line })
      }
    }
    for (const line of hunk.new_lines || []) {
      if (!(hunk.old_lines || []).includes(line)) {
        lines.push({ type: 'added', text: line })
      } else {
        lines.push({ type: 'context', text: line })
      }
    }
  }
  return lines
})

function copyCode() {
  navigator.clipboard.writeText(code.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

const diffColors: Record<string, string> = {
  added: 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300',
  removed: 'bg-red-50 text-red-900 dark:bg-red-950/30 dark:text-red-300',
  context: '',
  header: 'bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-400 font-medium',
}

const diffPrefix: Record<string, string> = {
  added: '+',
  removed: '-',
  context: ' ',
  header: '',
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-4 py-2">
      <div class="flex items-center gap-2">
        <FileCode class="h-4 w-4 text-muted-foreground" />
        <span class="text-sm font-mono">{{ title }}</span>
        <span class="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{{ language }}</span>
      </div>
      <div class="flex items-center gap-1">
        <Button
          v-if="diff"
          variant="ghost"
          size="sm"
          class="h-7 text-xs"
          :class="activeTab === 'diff' ? 'bg-muted' : ''"
          @click="activeTab = 'diff'"
        >
          <GitCompare class="mr-1 h-3 w-3" />
          Diff
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="h-7 text-xs"
          :class="activeTab === 'code' ? 'bg-muted' : ''"
          @click="activeTab = 'code'"
        >
          <FileCode class="mr-1 h-3 w-3" />
          Code
        </Button>
        <Button variant="ghost" size="icon" class="h-7 w-7" @click="copyCode">
          <Check v-if="copied" class="h-3.5 w-3.5 text-emerald-500" />
          <Copy v-else class="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>

    <!-- Code view -->
    <div v-if="activeTab === 'code'" class="flex-1 overflow-auto">
      <table class="w-full text-xs font-mono">
        <tbody>
          <tr v-for="(line, i) in codeLines" :key="i" class="hover:bg-muted/50">
            <td class="w-12 select-none px-3 py-0.5 text-right text-muted-foreground/50">{{ i + 1 }}</td>
            <td class="px-3 py-0.5 whitespace-pre">{{ line }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Diff view -->
    <div v-else-if="activeTab === 'diff'" class="flex-1 overflow-auto">
      <table class="w-full text-xs font-mono">
        <tbody>
          <tr v-for="(line, i) in diffLines" :key="i" :class="diffColors[line.type]">
            <td class="w-8 select-none px-2 py-0.5 text-center text-muted-foreground/50">{{ diffPrefix[line.type] }}</td>
            <td class="px-3 py-0.5 whitespace-pre">{{ line.text }}</td>
          </tr>
          <tr v-if="diffLines.length === 0">
            <td colspan="2" class="px-3 py-8 text-center text-muted-foreground">No diff available</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
