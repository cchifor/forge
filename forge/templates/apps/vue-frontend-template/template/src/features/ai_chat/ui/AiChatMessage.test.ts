import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('marked', () => ({
  marked: {
    setOptions: vi.fn(),
    parse: (text: string) => `<p>${text}</p>`,
  },
}))

vi.mock('dompurify', () => ({
  default: { sanitize: (html: string) => html },
}))

import AiChatMessage from './AiChatMessage.vue'

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
})
