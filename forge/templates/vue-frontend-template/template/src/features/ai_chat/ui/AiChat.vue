<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  X, Sparkles, Plus, Code2, ArrowUp, SlidersHorizontal, Monitor, ShieldCheck,
  ChevronDown, MessageSquarePlus, Settings, Maximize2,
} from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/shared/ui/dropdown-menu'
import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/shared/ui/tooltip'
import { useAiChat } from '../composables/useAiChat'
import AiChatMessage from './AiChatMessage.vue'
import UserPromptCard from './UserPromptCard.vue'

const MODEL_OPTIONS = [
  { value: 'openai:gpt-4.1', label: 'GPT-4.1' },
  { value: 'openai:gpt-4.1-mini', label: 'GPT-4.1 Mini' },
  { value: 'anthropic:claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
]

const route = useRoute()
const {
  messages,
  isGenerating,
  chatContext,
  pendingPrompt,
  closeChat,
  sendMessage,
  respondToPrompt,
  clearMessages,
} = useAiChat()

const inputText = ref('')
const selectedModel = ref('openai:gpt-4.1')
const approvalMode = ref<'default' | 'bypass'>('default')
const messagesContainer = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const chatPanel = ref<HTMLElement | null>(null)

const modelLabel = computed(() =>
  MODEL_OPTIONS.find(m => m.value === selectedModel.value)?.label ?? selectedModel.value,
)

const lastMessageIsAssistant = computed(() => {
  const msgs = messages.value
  return msgs.length > 0 && msgs[msgs.length - 1].role === 'assistant'
})

watch(
  () => route.meta.title,
  (title) => {
    chatContext.value = (title as string) || 'Current Page'
  },
  { immediate: true },
)

function autoResize() {
  const el = textareaEl.value
  if (!el) return
  // Collapse to 0 to get true scrollHeight independent of current height
  el.style.height = '0'
  const scrollH = el.scrollHeight
  const minH = 56 // ~2 lines + padding
  const panelH = chatPanel.value?.clientHeight ?? window.innerHeight
  const maxH = Math.floor(panelH * 0.5)
  const targetH = Math.max(minH, Math.min(scrollH, maxH))
  el.style.height = `${targetH}px`
  el.style.overflowY = scrollH > maxH ? 'auto' : 'hidden'
}

function handleSend() {
  const text = inputText.value.trim()
  if (!text || isGenerating.value) return
  sendMessage(text, { model: selectedModel.value, approval: approvalMode.value })
  inputText.value = ''
  nextTick(() => {
    if (textareaEl.value) {
      textareaEl.value.style.height = ''
      textareaEl.value.style.overflowY = 'hidden'
    }
    scrollToBottom()
  })
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else if (e.key === 'Enter' && e.shiftKey) {
    // Shift+Enter adds newline — resize on next tick after the newline is inserted
    nextTick(autoResize)
  }
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

watch(messages, () => nextTick(scrollToBottom), { deep: true })
</script>

<template>
  <aside ref="chatPanel" class="flex h-full flex-col bg-background">
    <!-- Header -->
    <div class="flex h-14 shrink-0 items-center justify-between border-b px-4">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-full ai-gradient">
          <Sparkles class="h-3.5 w-3.5 text-white" />
        </div>
        <span class="text-sm font-medium">AI Assistant</span>
      </div>

      <div class="flex items-center gap-0.5">
        <TooltipProvider :delay-duration="300">
          <Tooltip>
            <TooltipTrigger as-child>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground" @click="clearMessages">
                <MessageSquarePlus class="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">New Chat</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider :delay-duration="300">
          <Tooltip>
            <TooltipTrigger as-child>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground">
                <Settings class="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Settings</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider :delay-duration="300">
          <Tooltip>
            <TooltipTrigger as-child>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground">
                <Maximize2 class="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Maximize</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <div class="mx-1 h-5 w-px bg-border" />

        <Button variant="ghost" size="icon" class="h-8 w-8 interactive-press" @click="closeChat">
          <X class="h-4 w-4" />
        </Button>
      </div>
    </div>

    <!-- Messages -->
    <div
      ref="messagesContainer"
      class="flex flex-1 flex-col gap-4 overflow-y-auto scrollbar-thin p-4"
    >
      <div
        v-if="messages.length === 0 && !isGenerating"
        class="flex flex-1 flex-col items-center justify-center gap-3 text-center"
      >
        <div class="flex h-16 w-16 items-center justify-center rounded-full ai-gradient">
          <Sparkles class="h-8 w-8 text-white" />
        </div>
        <p class="text-sm text-muted-foreground">Ask me anything about this page.</p>
      </div>

      <AiChatMessage
        v-for="(msg, idx) in messages"
        :key="msg.id"
        :message="msg"
        :is-streaming="isGenerating && msg.role === 'assistant' && idx === messages.length - 1"
      />

      <!-- Thinking indicator -->
      <div
        v-if="isGenerating && !lastMessageIsAssistant"
        class="flex items-center gap-2"
      >
        <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full ai-gradient ai-glow transition-shadow">
          <Sparkles class="h-3.5 w-3.5 text-white" />
        </div>
        <span class="text-xs text-muted-foreground animate-pulse">Thinking...</span>
      </div>

      <!-- HITL prompt card -->
      <UserPromptCard
        v-if="pendingPrompt && !isGenerating"
        :prompt="pendingPrompt"
        :disabled="isGenerating"
        @respond="respondToPrompt"
      />
    </div>

    <!-- Input area -->
    <div class="border-t p-3">
      <div
        class="flex flex-col rounded-lg border bg-card transition-shadow"
        :class="{ 'ai-pulse': isGenerating }"
      >
        <textarea
          ref="textareaEl"
          v-model="inputText"
          placeholder="Describe what to build"
          rows="2"
          class="resize-none bg-transparent px-4 pt-3 pb-1 text-sm outline-none placeholder:text-muted-foreground scrollbar-thin"
          @keydown="handleKeydown"
          @input="autoResize"
        />

        <!-- Toolbar row -->
        <div class="flex items-center gap-1 px-2 pb-2">
          <TooltipProvider :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground">
                  <Plus class="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">Attach file</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <div class="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground">
            <Code2 class="h-3.5 w-3.5" />
            <span>Agent</span>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <button class="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                {{ modelLabel }}
                <ChevronDown class="h-3 w-3" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem
                v-for="opt in MODEL_OPTIONS"
                :key="opt.value"
                @click="selectedModel = opt.value"
              >
                {{ opt.label }}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <TooltipProvider :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon" class="h-7 w-7 text-muted-foreground">
                  <SlidersHorizontal class="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">Settings</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <div class="flex-1" />

          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7 shrink-0 rounded-full border border-border interactive-press"
            :disabled="!inputText.trim() || isGenerating"
            @click="handleSend"
          >
            <ArrowUp class="h-3.5 w-3.5 text-ai-from" />
          </Button>
        </div>
      </div>

      <!-- Session context row -->
      <div class="flex items-center gap-3 px-2 pt-2 text-[11px] text-muted-foreground">
        <div class="flex items-center gap-1">
          <Monitor class="h-3 w-3" />
          <span>Local</span>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <button class="flex items-center gap-1 hover:text-foreground transition-colors">
              <ShieldCheck class="h-3 w-3" />
              <span>{{ approvalMode === 'default' ? 'Default Approvals' : 'Bypass Approvals' }}</span>
              <ChevronDown class="h-2.5 w-2.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem @click="approvalMode = 'default'">
              Default Approvals
            </DropdownMenuItem>
            <DropdownMenuItem @click="approvalMode = 'bypass'">
              Bypass Approvals
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  </aside>
</template>
