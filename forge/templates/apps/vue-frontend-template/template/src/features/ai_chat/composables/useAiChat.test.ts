import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref, shallowRef } from 'vue'

// Mock crypto.randomUUID for deterministic IDs
let uuidCounter = 0
vi.stubGlobal('crypto', {
  randomUUID: () => `uuid-${++uuidCounter}`,
})

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

// Mock useAgentClient
const mockMessages = shallowRef<Array<{ id: string; role: string; content: string }>>([])
const mockIsRunning = ref(false)
const mockState = shallowRef({})
const mockCustomState = shallowRef({})
const mockError = ref<Error | null>(null)
const mockRunAgent = vi.fn()
const mockAddUserMessage = vi.fn((content: string) => {
  mockMessages.value = [
    ...mockMessages.value,
    { id: crypto.randomUUID(), role: 'user', content },
  ]
})
const mockResetThread = vi.fn(() => {
  mockMessages.value = []
  mockState.value = {}
  mockCustomState.value = {}
  mockError.value = null
})

vi.mock('./useAgentClient', () => ({
  useAgentClient: () => ({
    messages: mockMessages,
    isRunning: mockIsRunning,
    state: mockState,
    customState: mockCustomState,
    error: mockError,
    runAgent: mockRunAgent,
    addUserMessage: mockAddUserMessage,
    resetThread: mockResetThread,
  }),
}))

import { useAiChat } from './useAiChat'
import { useUiStore } from '@/shared/stores/ui.store'

describe('useAiChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
    uuidCounter = 0
    mockMessages.value = []
    mockIsRunning.value = false
    mockState.value = {}
    mockCustomState.value = {}
    mockError.value = null
    vi.clearAllMocks()
  })

  it('starts with empty messages', () => {
    const chat = useAiChat()
    expect(chat.messages.value).toHaveLength(0)
  })

  it('starts with isGenerating false', () => {
    const chat = useAiChat()
    expect(chat.isGenerating.value).toBe(false)
  })

  it('sendMessage adds a user message and runs agent', () => {
    const chat = useAiChat()
    chat.sendMessage('Hello')

    expect(mockAddUserMessage).toHaveBeenCalledWith('Hello')
    expect(mockRunAgent).toHaveBeenCalled()
  })

  it('messages are derived from agent client messages', () => {
    const chat = useAiChat()
    mockMessages.value = [
      { id: 'uuid-1', role: 'user', content: 'Hello' },
      { id: 'uuid-2', role: 'assistant', content: 'Hi there' },
    ]

    expect(chat.messages.value).toHaveLength(2)
    expect(chat.messages.value[0].role).toBe('user')
    expect(chat.messages.value[0].content).toBe('Hello')
    expect(chat.messages.value[1].role).toBe('assistant')
    expect(chat.messages.value[1].content).toBe('Hi there')
  })

  it('isGenerating reflects agent isRunning', () => {
    const chat = useAiChat()
    expect(chat.isGenerating.value).toBe(false)

    mockIsRunning.value = true
    expect(chat.isGenerating.value).toBe(true)
  })

  it('clearMessages delegates to agent resetThread', () => {
    const chat = useAiChat()
    chat.clearMessages()

    expect(mockResetThread).toHaveBeenCalled()
  })

  it('toggleChat delegates to uiStore.toggleChat', () => {
    const chat = useAiChat()
    const uiStore = useUiStore()
    const spy = vi.spyOn(uiStore, 'toggleChat')

    chat.toggleChat()
    expect(spy).toHaveBeenCalled()
  })

  it('openChat delegates to uiStore.setChatOpen(true)', () => {
    const chat = useAiChat()
    const uiStore = useUiStore()
    const spy = vi.spyOn(uiStore, 'setChatOpen')

    chat.openChat()
    expect(spy).toHaveBeenCalledWith(true)
  })

  it('closeChat delegates to uiStore.setChatOpen(false)', () => {
    const chat = useAiChat()
    const uiStore = useUiStore()
    const spy = vi.spyOn(uiStore, 'setChatOpen')

    chat.closeChat()
    expect(spy).toHaveBeenCalledWith(false)
  })
})
