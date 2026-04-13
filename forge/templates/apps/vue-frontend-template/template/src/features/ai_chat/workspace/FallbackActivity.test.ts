import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import FallbackActivity from './FallbackActivity.vue'
import type { WorkspaceActivity } from '../types'

function makeActivity(
  activityType: string,
  content: Record<string, any> = {},
): WorkspaceActivity {
  return {
    engine: 'ag-ui',
    activityType,
    messageId: 'msg-1',
    content,
  }
}

describe('FallbackActivity', () => {
  it('shows activityType as heading', () => {
    const wrapper = mount(FallbackActivity, {
      props: { activity: makeActivity('custom_widget') },
    })

    expect(wrapper.find('h3').text()).toBe('custom_widget')
  })

  it('renders JSON content in pre block', () => {
    const content = { key: 'value', count: 42 }
    const wrapper = mount(FallbackActivity, {
      props: { activity: makeActivity('debug_info', content) },
    })

    const pre = wrapper.find('pre')
    expect(pre.exists()).toBe(true)
    expect(pre.text()).toBe(JSON.stringify(content, null, 2))
  })

  it('handles empty content', () => {
    const wrapper = mount(FallbackActivity, {
      props: { activity: makeActivity('empty_panel', {}) },
    })

    const pre = wrapper.find('pre')
    expect(pre.exists()).toBe(true)
    expect(pre.text()).toBe('{}')
  })
})
