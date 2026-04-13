import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolCallStatus from './ToolCallStatus.vue'

describe('ToolCallStatus', () => {
  it('shows tool name text', () => {
    const wrapper = mount(ToolCallStatus, {
      props: { toolName: 'read_file', status: 'pending' },
    })

    expect(wrapper.text()).toContain('read_file')
  })

  it('status running shows loader icon', () => {
    const wrapper = mount(ToolCallStatus, {
      props: { toolName: 'search', status: 'running' },
    })

    expect(wrapper.find('.animate-spin').exists()).toBe(true)
    expect(wrapper.text()).toContain('running')
  })

  it('status completed shows check icon', () => {
    const wrapper = mount(ToolCallStatus, {
      props: { toolName: 'search', status: 'completed' },
    })

    expect(wrapper.find('.text-green-500').exists()).toBe(true)
    expect(wrapper.text()).toContain('completed')
  })

  it('status error shows X icon', () => {
    const wrapper = mount(ToolCallStatus, {
      props: { toolName: 'search', status: 'error' },
    })

    expect(wrapper.find('.text-red-500').exists()).toBe(true)
    expect(wrapper.text()).toContain('error')
  })

  it('status pending shows clock icon', () => {
    const wrapper = mount(ToolCallStatus, {
      props: { toolName: 'search', status: 'pending' },
    })

    expect(wrapper.find('.text-muted-foreground').exists()).toBe(true)
    expect(wrapper.text()).toContain('pending')
  })
})
