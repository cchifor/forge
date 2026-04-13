import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ApprovalReview from './ApprovalReview.vue'
import type { WorkspaceActivity } from '../types'

function makeActivity(content: Record<string, any> = {}): WorkspaceActivity {
  return {
    engine: 'ag-ui',
    activityType: 'tool_approval',
    messageId: 'msg-1',
    content,
  }
}

describe('ApprovalReview', () => {
  it('displays tool name from activity.content.toolName', () => {
    const wrapper = mount(ApprovalReview, {
      props: { activity: makeActivity({ toolName: 'file_write', toolCallId: 'tc-1' }) },
    })

    expect(wrapper.text()).toContain('file_write')
  })

  it('shows Unknown Tool when toolName is missing', () => {
    const wrapper = mount(ApprovalReview, {
      props: { activity: makeActivity({ toolCallId: 'tc-1' }) },
    })

    expect(wrapper.text()).toContain('Unknown Tool')
  })

  it('approve button emits action with approved: true', async () => {
    const wrapper = mount(ApprovalReview, {
      props: { activity: makeActivity({ toolName: 'exec', toolCallId: 'tc-42' }) },
    })

    const buttons = wrapper.findAll('button')
    const approveBtn = buttons.find(b => b.text().includes('Approve'))!
    await approveBtn.trigger('click')

    const emitted = wrapper.emitted('action')!
    expect(emitted[0][0]).toMatchObject({
      type: 'tool_approval',
      data: { toolCallId: 'tc-42', approved: true },
    })
  })

  it('reject button emits action with approved: false', async () => {
    const wrapper = mount(ApprovalReview, {
      props: { activity: makeActivity({ toolName: 'exec', toolCallId: 'tc-42' }) },
    })

    const buttons = wrapper.findAll('button')
    const rejectBtn = buttons.find(b => b.text().includes('Reject'))!
    await rejectBtn.trigger('click')

    const emitted = wrapper.emitted('action')!
    expect(emitted[0][0]).toMatchObject({
      type: 'tool_approval',
      data: { toolCallId: 'tc-42', approved: false },
    })
  })

  it('arguments formatted as JSON', () => {
    const args = { path: '/tmp/out.txt', content: 'hello' }
    const wrapper = mount(ApprovalReview, {
      props: { activity: makeActivity({ toolName: 'write', arguments: args }) },
    })

    const pre = wrapper.find('pre')
    expect(pre.text()).toBe(JSON.stringify(args, null, 2))
  })

  it('diff shown when present in content', () => {
    const diff = '--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old\n+new'
    const wrapper = mount(ApprovalReview, {
      props: { activity: makeActivity({ toolName: 'edit', diff }) },
    })

    const preBlocks = wrapper.findAll('pre')
    expect(preBlocks.length).toBeGreaterThanOrEqual(2)
    expect(preBlocks[preBlocks.length - 1].text()).toContain('+new')
  })
})
