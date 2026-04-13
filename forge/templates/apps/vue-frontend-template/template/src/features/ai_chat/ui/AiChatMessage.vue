<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { Sparkles, Wrench, Copy, Check, Pencil } from 'lucide-vue-next'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ breaks: true, gfm: true })

function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text) as string)
}

const props = defineProps<{
  message: { id: string; role: string; content: string }
  isStreaming?: boolean
}>()

const emit = defineEmits<{
  edit: [payload: { id: string; content: string }]
}>()

const copied = ref(false)
const editing = ref(false)
const editText = ref('')
const editTextarea = ref<HTMLTextAreaElement | null>(null)

const renderedContent = computed(() =>
  props.message.content ? renderMarkdown(props.message.content) : '',
)

async function copyMessage() {
  if (!props.message.content) return
  await navigator.clipboard.writeText(props.message.content)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function startEdit() {
  editText.value = props.message.content
  editing.value = true
  nextTick(() => editTextarea.value?.focus())
}

function cancelEdit() {
  editing.value = false
}

function submitEdit() {
  const trimmed = editText.value.trim()
  if (!trimmed) return
  editing.value = false
  emit('edit', { id: props.message.id, content: trimmed })
}
</script>

<template>
  <!-- User message -->
  <div v-if="props.message.role === 'user'" class="group flex justify-end">
    <div class="flex max-w-[80%] flex-col items-end">
      <!-- Action buttons above bubble -->
      <div
        v-if="props.message.content && !editing"
        class="mb-1 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100"
      >
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          :aria-label="copied ? 'Copied' : 'Copy message'"
          @click="copyMessage"
        >
          <Check v-if="copied" class="h-3.5 w-3.5" />
          <Copy v-else class="h-3.5 w-3.5" />
        </button>
        <button
          class="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          aria-label="Edit message"
          @click="startEdit"
        >
          <Pencil class="h-3.5 w-3.5" />
        </button>
      </div>
      <!-- Edit mode -->
      <div v-if="editing" class="w-full">
        <textarea
          ref="editTextarea"
          v-model="editText"
          class="w-full resize-none rounded-2xl border bg-muted px-3.5 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-1 focus:ring-ring"
          rows="3"
          @keydown.enter.exact.prevent="submitEdit"
          @keydown.escape="cancelEdit"
        />
        <div class="mt-1 flex justify-end gap-1.5">
          <button
            class="rounded px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
            @click="cancelEdit"
          >
            Cancel
          </button>
          <button
            class="rounded bg-primary px-2.5 py-1 text-xs text-primary-foreground hover:bg-primary/90 transition-colors"
            :disabled="!editText.trim()"
            @click="submitEdit"
          >
            Send
          </button>
        </div>
      </div>
      <!-- Display mode -->
      <div
        v-else
        class="rounded-2xl bg-muted px-3.5 py-2 text-sm leading-relaxed text-foreground"
      >
        {{ props.message.content }}
      </div>
    </div>
  </div>

  <!-- Assistant message -->
  <div v-else-if="props.message.role === 'assistant'" class="group flex gap-2.5" role="article" aria-label="Assistant message">
    <div class="flex h-5 w-5 shrink-0 items-center justify-center mt-0.5">
      <Sparkles class="h-4 w-4 text-ai-from" />
    </div>
    <div class="flex min-w-0 flex-1 flex-col gap-1">
      <div
        v-if="props.message.content"
        class="prose prose-sm dark:prose-invert max-w-none text-foreground"
        v-html="renderedContent"
      />
      <div
        v-else-if="props.isStreaming"
        class="text-sm text-muted-foreground animate-pulse"
      >
        Thinking...
      </div>
      <span
        v-if="props.isStreaming && props.message.content"
        class="inline-block w-1.5 h-4 bg-foreground/50 animate-pulse"
      />
      <button
        v-if="props.message.content && !props.isStreaming"
        class="mt-1 flex items-center gap-1 self-start text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        :aria-label="copied ? 'Copied' : 'Copy message'"
        @click="copyMessage"
      >
        <Check v-if="copied" class="h-3 w-3" />
        <Copy v-else class="h-3 w-3" />
        {{ copied ? 'Copied' : 'Copy' }}
      </button>
    </div>
  </div>

  <!-- Tool message -->
  <div v-else-if="props.message.role === 'tool'" class="flex gap-3">
    <div
      class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted"
    >
      <Wrench class="h-3.5 w-3.5 text-muted-foreground" />
    </div>
    <div class="flex max-w-[80%] flex-col gap-0.5">
      <span class="text-xs font-medium text-muted-foreground">Tool</span>
      <div class="rounded-lg border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
        {{ props.message.content }}
      </div>
    </div>
  </div>

  <!-- Default / unknown role -->
  <div v-else class="flex gap-3">
    <div class="flex max-w-[80%] flex-col gap-0.5 pl-10">
      <div class="text-sm text-muted-foreground">
        {{ props.message.content }}
      </div>
    </div>
  </div>
</template>
