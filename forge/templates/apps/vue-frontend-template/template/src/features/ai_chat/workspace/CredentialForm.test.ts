import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CredentialForm from './CredentialForm.vue'
import type { WorkspaceActivity } from '../types'

function makeActivity(content: Record<string, any> = {}): WorkspaceActivity {
  return {
    engine: 'ag-ui',
    activityType: 'credential_request',
    messageId: 'msg-1',
    content,
  }
}

describe('CredentialForm', () => {
  it('renders form fields from activity.content.fields', () => {
    const fields = [
      { name: 'username', label: 'Username', type: 'text', required: true },
      { name: 'token', label: 'API Token', type: 'password', required: true },
    ]
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({ fields }) },
    })

    const inputs = wrapper.findAll('input')
    expect(inputs).toHaveLength(2)
    expect(wrapper.text()).toContain('Username')
    expect(wrapper.text()).toContain('API Token')
  })

  it('defaults to a single password field when no fields specified', () => {
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({}) },
    })

    const inputs = wrapper.findAll('input')
    expect(inputs).toHaveLength(1)
    expect(wrapper.text()).toContain('Password')
    expect(inputs[0].attributes('type')).toBe('password')
  })

  it('submit emits action with type submit_credentials', async () => {
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({}) },
    })

    await wrapper.find('form').trigger('submit')

    const emitted = wrapper.emitted('action')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toMatchObject({ type: 'submit_credentials' })
  })

  it('form values are included in emitted data', async () => {
    const fields = [
      { name: 'username', label: 'Username', type: 'text' },
      { name: 'password', label: 'Password', type: 'password' },
    ]
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({ fields }) },
    })

    await wrapper.find('input#username').setValue('admin')
    await wrapper.find('input#password').setValue('secret')
    await wrapper.find('form').trigger('submit')

    const emitted = wrapper.emitted('action')!
    expect(emitted[0][0]).toMatchObject({
      type: 'submit_credentials',
      data: { username: 'admin', password: 'secret' },
    })
  })

  it('password visibility toggle works', async () => {
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({}) },
    })

    const input = wrapper.find('input')
    expect(input.attributes('type')).toBe('password')

    await wrapper.find('button[type="button"]').trigger('click')
    expect(input.attributes('type')).toBe('text')

    await wrapper.find('button[type="button"]').trigger('click')
    expect(input.attributes('type')).toBe('password')
  })

  it('required field indicator shown', () => {
    const fields = [
      { name: 'token', label: 'Token', type: 'text', required: true },
    ]
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({ fields }) },
    })

    expect(wrapper.find('.text-destructive').exists()).toBe(true)
    expect(wrapper.find('.text-destructive').text()).toBe('*')
  })

  it('empty form still submits', async () => {
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({}) },
    })

    await wrapper.find('form').trigger('submit')

    const emitted = wrapper.emitted('action')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toMatchObject({ type: 'submit_credentials', data: {} })
  })

  it('multiple fields render correctly', () => {
    const fields = [
      { name: 'host', label: 'Host', type: 'text' },
      { name: 'port', label: 'Port', type: 'text' },
      { name: 'user', label: 'User', type: 'text' },
      { name: 'pass', label: 'Pass', type: 'password', required: true },
    ]
    const wrapper = mount(CredentialForm, {
      props: { activity: makeActivity({ fields }) },
    })

    expect(wrapper.findAll('input')).toHaveLength(4)
    expect(wrapper.text()).toContain('Host')
    expect(wrapper.text()).toContain('Port')
    expect(wrapper.text()).toContain('User')
    expect(wrapper.text()).toContain('Pass')
    // Only the password field should have a visibility toggle button
    const toggleButtons = wrapper.findAll('button[type="button"]')
    expect(toggleButtons).toHaveLength(1)
  })
})
