import { afterEach, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ProfilePage from '../../src/features/profile/ui/ProfilePage.vue'
import { AvatarFallback } from '../../src/shared/ui/avatar'
import { Badge } from '../../src/shared/ui/badge'
import { useAuth } from '../../src/shared/composables/useAuth'

afterEach(() => vi.unstubAllEnvs())

it('shows the signed-in identity and clears it on sign out', async () => {
  // Both authentication variants sign in the development user in this mode.
  vi.stubEnv('VITE_AUTH_DISABLED', 'true')
  const auth = useAuth()
  await auth.init()
  const wrapper = mount(ProfilePage)
  expect(wrapper.get('h2').text()).toBe('Dev User')
  expect(wrapper.text()).toContain('@dev-user')
  expect(wrapper.getComponent(AvatarFallback).text()).toBe('DU')
  expect(wrapper.findAllComponents(Badge).map(badge => badge.text())).toEqual(['admin', 'user'])
  for (const [label, value] of [
    ['Email', 'dev@localhost'],
    ['User ID', '00000000-0000-0000-0000-000000000001'],
    ['Customer ID', '00000000-0000-0000-0000-000000000001'],
    ['Organization', 'N/A'],
  ]) {
    expect(wrapper.text()).toContain(label + value)
  }

  await wrapper.findAll('button').find(button => button.text() === 'Sign Out')!.trigger('click')
  expect(auth.user.value).toBeNull()
  expect(wrapper.getComponent(AvatarFallback).text()).toBe('?')
  expect(wrapper.findAllComponents(Badge)).toHaveLength(0)
  expect(wrapper.text()).not.toContain('dev@localhost')
  wrapper.unmount()
})
