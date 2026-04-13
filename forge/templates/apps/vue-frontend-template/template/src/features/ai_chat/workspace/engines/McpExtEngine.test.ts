import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import type { WorkspaceActivity } from '../../types'

const mockBridge = {
  connect: vi.fn().mockResolvedValue(undefined),
  sendToolInput: vi.fn(),
  sendSandboxResourceReady: vi.fn(),
  sendHostContextChange: vi.fn(),
  teardownResource: vi.fn().mockResolvedValue(undefined),
  oninitialized: null as any,
  onmessage: null as any,
  onopenlink: null as any,
  onsizechange: null as any,
}

vi.mock('@modelcontextprotocol/ext-apps/app-bridge', () => ({
  AppBridge: vi.fn().mockImplementation(() => mockBridge),
  PostMessageTransport: vi.fn(),
}))

import McpExtEngine from './McpExtEngine.vue'
import { AppBridge } from '@modelcontextprotocol/ext-apps/app-bridge'

function makeActivity(content: Record<string, any> = {}): WorkspaceActivity {
  return {
    engine: 'mcp-ext',
    activityType: 'mcp_panel',
    messageId: 'msg-1',
    content,
  }
}

describe('McpExtEngine', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockBridge.connect.mockResolvedValue(undefined)
    mockBridge.teardownResource.mockResolvedValue(undefined)
    mockBridge.oninitialized = null
    mockBridge.onmessage = null
    mockBridge.onopenlink = null
    mockBridge.onsizechange = null
  })

  it('renders iframe element', () => {
    const activity = makeActivity({ entryUrl: 'https://example.com/app' })

    const wrapper = mount(McpExtEngine, { props: { activity } })

    expect(wrapper.find('iframe').exists()).toBe(true)
  })

  it('iframe has correct sandbox attribute', () => {
    const activity = makeActivity({ entryUrl: 'https://example.com/app' })

    const wrapper = mount(McpExtEngine, { props: { activity } })

    const iframe = wrapper.find('iframe')
    expect(iframe.attributes('sandbox')).toBe('allow-scripts allow-same-origin allow-forms')
  })

  it('AppBridge constructor called on mount', async () => {
    const activity = makeActivity({ entryUrl: 'https://example.com/app' })

    mount(McpExtEngine, {
      props: { activity },
      attachTo: document.body,
    })
    await flushPromises()

    expect(AppBridge).toHaveBeenCalled()
  })

  it('iframe src set from activity.content.entryUrl', () => {
    const activity = makeActivity({ entryUrl: 'https://example.com/widget' })

    const wrapper = mount(McpExtEngine, { props: { activity } })

    const iframe = wrapper.find('iframe')
    expect(iframe.attributes('src')).toBe('https://example.com/widget')
  })

  it('sendSandboxResourceReady is called when activity has html content', async () => {
    const activity = makeActivity({
      entryUrl: 'https://example.com/app',
      html: '<h1>Hello</h1>',
      csp: "default-src 'self'",
      permissions: {},
    })

    mount(McpExtEngine, {
      props: { activity },
      attachTo: document.body,
    })
    await flushPromises()

    expect(mockBridge.sendSandboxResourceReady).toHaveBeenCalledWith({
      html: '<h1>Hello</h1>',
      csp: "default-src 'self'",
      permissions: {},
    })
  })

  it('teardownResource is called on unmount', async () => {
    const activity = makeActivity({ entryUrl: 'https://example.com/app' })

    const wrapper = mount(McpExtEngine, {
      props: { activity },
      attachTo: document.body,
    })
    await flushPromises()

    wrapper.unmount()
    await flushPromises()

    expect(mockBridge.teardownResource).toHaveBeenCalledWith({})
  })
})
