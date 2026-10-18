import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ToolRegistry from './ToolRegistry.vue'

afterEach(() => vi.unstubAllGlobals())

function serve(reply: () => Promise<Response>) {
  const fetchMock = vi.fn(reply)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

it('lists the tools of every configured server', async () => {
  const fetchMock = serve(() => Promise.resolve(Response.json([
    { server: 'filesystem', name: 'read_file', description: 'Read a file', input_schema: {} },
    { server: 'search', name: 'query', description: 'Search the web', input_schema: {} },
  ])))
  const wrapper = mount(ToolRegistry)
  expect(wrapper.text()).toContain('Loading...')

  await flushPromises()
  expect(fetchMock).toHaveBeenCalledWith('/mcp/tools')
  const items = wrapper.findAll('li')
  expect(items.map((item) => item.get('.server-badge').text())).toEqual(['filesystem', 'search'])
  expect(items[0].text()).toContain('read_file')
  expect(items[0].text()).toContain('Read a file')
})

it('explains an empty registry', async () => {
  serve(() => Promise.resolve(Response.json([])))
  const wrapper = mount(ToolRegistry)
  await flushPromises()
  expect(wrapper.text()).toContain('No MCP servers configured')
})

it.each([
  ['an error status', () => Promise.resolve(new Response(null, { status: 503 })), 'HTTP 503'],
  ['a network failure', () => Promise.reject(new TypeError('offline')), 'offline'],
])('reports %s', async (_case, reply, message) => {
  serve(reply)
  const wrapper = mount(ToolRegistry)
  await flushPromises()
  expect(wrapper.get('.error').text()).toBe(`Failed to load tools: ${message}`)
  expect(wrapper.text()).not.toContain('Loading...')
})
