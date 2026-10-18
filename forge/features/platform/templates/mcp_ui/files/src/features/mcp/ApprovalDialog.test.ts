import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ApprovalDialog from './ApprovalDialog.vue'

const call = { toolName: 'read_file', server: 'filesystem', inputPreview: '{"path": "notes.md"}' }

it('shows the call and approves it, remembering the choice by default', async () => {
  const wrapper = mount(ApprovalDialog, { props: { ...call, defaultMode: 'prompt-once' } })
  expect(wrapper.text()).toContain('filesystem · read_file')
  expect(wrapper.get('.input-preview').text()).toBe(call.inputPreview)
  expect((wrapper.get('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)

  await wrapper.get('.approve').trigger('click')
  expect(wrapper.emitted('approve')).toEqual([[true]])
})

it('asks every time in prompt-every mode unless the user opts in', async () => {
  const wrapper = mount(ApprovalDialog, { props: { ...call, defaultMode: 'prompt-every' } })
  await wrapper.get('.approve').trigger('click')
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('.approve').trigger('click')
  expect(wrapper.emitted('approve')).toEqual([[false], [true]])
})

it('denies the call', async () => {
  const wrapper = mount(ApprovalDialog, { props: { ...call, defaultMode: 'auto' } })
  await wrapper.get('.deny').trigger('click')
  expect(wrapper.emitted('deny')).toEqual([[]])
  expect(wrapper.emitted('approve')).toBeUndefined()
})
