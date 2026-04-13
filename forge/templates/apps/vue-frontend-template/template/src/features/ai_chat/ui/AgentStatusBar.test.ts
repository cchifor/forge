import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

vi.mock('@/features/ai_chat/composables/useAgentClient', () => ({
  useAgentClient: () => ({
    isRunning: ref(false),
    customState: ref({ cost: { run_usd: 0.0042 }, context: { usage_pct: 65 } }),
  }),
}))

import AgentStatusBar from './AgentStatusBar.vue'

describe('AgentStatusBar', () => {
  it('shows idle indicator when not running', () => {
    const wrapper = mount(AgentStatusBar)

    expect(wrapper.text()).toContain('Idle')
    expect(wrapper.find('.bg-green-500').exists()).toBe(true)
  })

  it('shows running indicator when running', async () => {
    // Re-mock with isRunning = true
    const mod = await import('@/features/ai_chat/composables/useAgentClient')
    ;(mod.useAgentClient as any) = () => ({
      isRunning: ref(true),
      customState: ref({ cost: { run_usd: 0.0042 }, context: { usage_pct: 65 } }),
    })

    const wrapper = mount(AgentStatusBar)

    expect(wrapper.text()).toContain('Running')
    expect(wrapper.find('.animate-spin').exists()).toBe(true)
  })

  it('formats cost as $0.0042', async () => {
    const mod = await import('@/features/ai_chat/composables/useAgentClient')
    ;(mod.useAgentClient as any) = () => ({
      isRunning: ref(false),
      customState: ref({ cost: { run_usd: 0.0042 }, context: { usage_pct: 65 } }),
    })

    const wrapper = mount(AgentStatusBar)

    expect(wrapper.text()).toContain('$0.0042')
  })

  it('shows context percentage', async () => {
    const mod = await import('@/features/ai_chat/composables/useAgentClient')
    ;(mod.useAgentClient as any) = () => ({
      isRunning: ref(false),
      customState: ref({ cost: { run_usd: 0.01 }, context: { usage_pct: 65 } }),
    })

    const wrapper = mount(AgentStatusBar)

    expect(wrapper.text()).toContain('65%')
  })

  it('handles missing cost gracefully', async () => {
    const mod = await import('@/features/ai_chat/composables/useAgentClient')
    ;(mod.useAgentClient as any) = () => ({
      isRunning: ref(false),
      customState: ref({ context: { usage_pct: 50 } }),
    })

    const wrapper = mount(AgentStatusBar)

    expect(wrapper.text()).not.toContain('Cost')
    expect(wrapper.text()).toContain('50%')
  })

  it('handles missing context gracefully', async () => {
    const mod = await import('@/features/ai_chat/composables/useAgentClient')
    ;(mod.useAgentClient as any) = () => ({
      isRunning: ref(false),
      customState: ref({ cost: { run_usd: 0.005 } }),
    })

    const wrapper = mount(AgentStatusBar)

    expect(wrapper.text()).not.toContain('Context')
    expect(wrapper.text()).toContain('$0.0050')
  })
})
