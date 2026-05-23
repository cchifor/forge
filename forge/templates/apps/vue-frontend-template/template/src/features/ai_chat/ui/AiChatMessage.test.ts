import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const { parseSpy } = vi.hoisted(() => ({
  parseSpy: vi.fn((text: string) => `<p>${text}</p>`),
}))

vi.mock('marked', () => ({
  marked: {
    setOptions: vi.fn(),
    parse: (text: string) => parseSpy(text),
  },
}))

vi.mock('dompurify', () => ({
  default: { sanitize: (html: string) => html },
}))

import AiChatMessage from './AiChatMessage.vue'

beforeEach(() => {
  parseSpy.mockClear()
})

function makeMessage(role: string, content: string, id = 'msg-1') {
  return { id, role, content }
}

describe('AiChatMessage', () => {
  it('user role renders right-aligned bubble', () => {
    const wrapper = mount(AiChatMessage, {
      props: { message: makeMessage('user', 'Hello world') },
    })

    expect(wrapper.find('.justify-end').exists()).toBe(true)
    expect(wrapper.text()).toContain('Hello world')
  })

  it('assistant role renders with sparkles icon', () => {
    const wrapper = mount(AiChatMessage, {
      props: { message: makeMessage('assistant', 'Hi there') },
    })

    expect(wrapper.find('.justify-end').exists()).toBe(false)
    expect(wrapper.find('[role="article"]').exists()).toBe(true)
  })

  it('tool role renders compact card with label', () => {
    const wrapper = mount(AiChatMessage, {
      props: { message: makeMessage('tool', 'file read result') },
    })

    expect(wrapper.find('.bg-muted\\/50').exists()).toBe(true)
    expect(wrapper.text()).toContain('Tool')
  })

  it('streaming prop shows pulse animation', () => {
    const wrapper = mount(AiChatMessage, {
      props: {
        message: makeMessage('assistant', 'Generating...'),
        isStreaming: true,
      },
    })

    expect(wrapper.find('.animate-pulse').exists()).toBe(true)
  })

  it('message content displayed', () => {
    const wrapper = mount(AiChatMessage, {
      props: { message: makeMessage('user', 'My important question') },
    })

    expect(wrapper.text()).toContain('My important question')
  })

  it('user message shows copy and edit buttons on hover', () => {
    const wrapper = mount(AiChatMessage, {
      props: { message: makeMessage('user', 'Hello') },
    })

    // Buttons exist but hidden (opacity-0 until hover)
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(2)
  })

  it('default role renders generic layout', () => {
    const wrapper = mount(AiChatMessage, {
      props: { message: makeMessage('system', 'System info') },
    })

    expect(wrapper.find('.justify-end').exists()).toBe(false)
    expect(wrapper.text()).toContain('System info')
  })

  it('empty content with streaming shows Thinking...', () => {
    const wrapper = mount(AiChatMessage, {
      props: {
        message: makeMessage('assistant', ''),
        isStreaming: true,
      },
    })

    expect(wrapper.text()).toContain('Thinking...')
  })

  describe('streaming debounce', () => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('collapses 10 rapid token updates within 50ms into <= 2 markdown parses', async () => {
      vi.useFakeTimers()
      const message = makeMessage('assistant', 'a')
      const wrapper = mount(AiChatMessage, {
        props: { message, isStreaming: true },
      })
      // Initial mount parses content once for the cached HTML.
      const initialCalls = parseSpy.mock.calls.length

      // Simulate 10 token deltas arriving in 5ms increments — all inside the
      // 50ms debounce window.
      for (let i = 0; i < 10; i++) {
        message.content += `b${i}`
        await wrapper.setProps({
          message: { ...message },
          isStreaming: true,
        })
        vi.advanceTimersByTime(5)
      }

      // Window closes at 50ms — debounce fires exactly one render.
      vi.advanceTimersByTime(50)
      await flushPromises()

      const renderCalls = parseSpy.mock.calls.length - initialCalls
      expect(renderCalls).toBeLessThanOrEqual(2)
    })

    it('flushes immediately when streaming transitions to false', async () => {
      vi.useFakeTimers()
      const message = makeMessage('assistant', 'partial token')
      const wrapper = mount(AiChatMessage, {
        props: { message, isStreaming: true },
      })
      const baseline = parseSpy.mock.calls.length

      message.content = 'partial token + final'
      await wrapper.setProps({
        message: { ...message },
        isStreaming: true,
      })
      // Do not advance the debounce window; flip isStreaming -> false.
      await wrapper.setProps({
        message: { ...message },
        isStreaming: false,
      })
      await flushPromises()

      // Final tokens rendered within frame, not delayed by the debounce timer.
      expect(parseSpy.mock.calls.length).toBeGreaterThan(baseline)
      expect(wrapper.html()).toContain('partial token + final')
    })
  })
})
