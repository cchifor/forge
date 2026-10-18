import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { VueQueryPlugin } from '@tanstack/vue-query'
import { http, HttpResponse } from 'msw'
import HomePage from '../../src/features/home/ui/HomePage.vue'
import { queryClient } from '../../src/app/providers/query-client'
import { server } from '../../src/shared/mocks/node'
import { useAuth } from '../../src/shared/composables/useAuth'

const Empty = defineComponent({ render: () => null })
let wrapper: VueWrapper | undefined
let router: Router

beforeEach(async () => {
  vi.stubEnv('VITE_AUTH_DISABLED', 'true')
  await useAuth().init()
  router = createRouter({
    history: createMemoryHistory(),
    routes: ['/', '/items', '/items/new', '/profile', '/settings'].map(path => ({ path, component: Empty })),
  })
  await router.push('/')
  wrapper = mount(HomePage, { global: { plugins: [router, [VueQueryPlugin, { queryClient }]] } })
})

afterEach(() => {
  wrapper?.unmount()
  queryClient.clear()
  vi.unstubAllEnvs()
})

it('greets the user and reports service information and readiness', async () => {
  expect(wrapper!.get('h1').text()).toBe('Welcome back, Dev!')
  await vi.waitFor(() => expect(wrapper!.text()).toContain('My Service'))
  expect(wrapper!.text()).toContain('v0.1.0')
  expect(wrapper!.text()).toContain('A microservice template')
  await vi.waitFor(() => expect(wrapper!.text()).toContain('2.5ms latency'))
  expect(wrapper!.findAll('p.capitalize').map(name => name.text())).toEqual(['database'])
  expect(wrapper!.text()).toContain('UP')
})

it('navigates from every quick action', async () => {
  const targets: string[] = []
  for (const label of ['Browse Items', 'Create Item', 'View Profile', 'Settings']) {
    const action = wrapper!.findAll('button').find(button => button.text() === label)!
    await action.trigger('click')
    await flushPromises()
    targets.push(router.currentRoute.value.path)
  }
  expect(targets).toEqual(['/items', '/items/new', '/profile', '/settings'])
})

it('shows degraded components reported by the readiness probe', async () => {
  queryClient.clear()
  wrapper!.unmount()
  server.use(http.get('*/v1/health/ready', () => HttpResponse.json({
    status: 'DEGRADED',
    components: { cache: { status: 'DOWN', latency_ms: null, details: { error: 'unreachable' } } },
    system_info: { platform: 'test' },
  })))
  wrapper = mount(HomePage, { global: { plugins: [router, [VueQueryPlugin, { queryClient }]] } })
  await vi.waitFor(() => expect(wrapper!.text()).toContain('cache'))
  expect(wrapper!.text()).not.toContain('latency')
  expect(wrapper!.text()).toContain('DEGRADED')
  expect(wrapper!.text()).toContain('DOWN')
})
