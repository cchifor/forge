// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { flushSync, mount, unmount } from 'svelte'
import DynamicForm from '../src/components/DynamicForm.svelte'

describe('DynamicForm checkbox binding', () => {
  it.each([true, false])('preserves boolean default %s and emits a changed value', async (initial) => {
    const target = document.createElement('div')
    document.body.append(target)
    const onsubmit = vi.fn()
    const component = mount(DynamicForm, {
      target,
      props: {
        title: 'Settings',
        fields: [{ name: 'enabled', label: 'Enabled', type: 'checkbox', default: initial }],
        onsubmit,
      },
    })
    try {
      flushSync()
      const input = target.querySelector('input')!
      expect(input.checked).toBe(initial)
      input.checked = !initial
      input.dispatchEvent(new Event('change', { bubbles: true }))
      flushSync()
      target.querySelector('form')!.dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true }),
      )
      expect(onsubmit).toHaveBeenCalledWith({ enabled: !initial })
    } finally {
      await unmount(component)
      target.remove()
    }
  })
})
