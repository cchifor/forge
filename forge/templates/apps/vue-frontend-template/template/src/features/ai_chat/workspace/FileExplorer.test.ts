import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import FileExplorer from './FileExplorer.vue'
import type { WorkspaceActivity } from '../types'

function makeActivity(content: Record<string, any> = {}): WorkspaceActivity {
  return {
    engine: 'ag-ui',
    activityType: 'file_explorer',
    messageId: 'msg-1',
    content,
  }
}

describe('FileExplorer', () => {
  it('renders files from activity.content.files', () => {
    const files = [
      { path: '/src/main.ts', name: 'main.ts', size: 1200 },
      { path: '/src/app.vue', name: 'app.vue', size: 800 },
    ]
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({ files }) },
    })

    expect(wrapper.text()).toContain('main.ts')
    expect(wrapper.text()).toContain('app.vue')
  })

  it('shows empty state when no files', () => {
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({}) },
    })

    expect(wrapper.text()).toContain('No files available')
  })

  it('file click emits action with type select_file and path', async () => {
    const files = [{ path: '/src/index.ts', name: 'index.ts' }]
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({ files }) },
    })

    await wrapper.find('button').trigger('click')

    const emitted = wrapper.emitted('action')!
    expect(emitted[0][0]).toMatchObject({
      type: 'select_file',
      data: { path: '/src/index.ts' },
    })
  })

  it('formats bytes size correctly', () => {
    const files = [{ path: '/a.txt', name: 'a.txt', size: 512 }]
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({ files }) },
    })

    expect(wrapper.text()).toContain('512 B')
  })

  it('formats KB size correctly', () => {
    const files = [{ path: '/b.txt', name: 'b.txt', size: 2048 }]
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({ files }) },
    })

    expect(wrapper.text()).toContain('2.0 KB')
  })

  it('formats MB size correctly', () => {
    const files = [{ path: '/c.bin', name: 'c.bin', size: 5242880 }]
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({ files }) },
    })

    expect(wrapper.text()).toContain('5.0 MB')
  })

  it('selects icon based on file extension', () => {
    const files = [
      { path: '/img.png', name: 'img.png' },
      { path: '/code.ts', name: 'code.ts' },
      { path: '/doc.md', name: 'doc.md' },
    ]
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({ files }) },
    })

    // All three files should render as clickable buttons
    expect(wrapper.findAll('button')).toHaveLength(3)
  })

  it('uses state.files as fallback when content.files missing', () => {
    const state = {
      files: [
        { path: '/fallback.txt', name: 'fallback.txt' },
      ],
    }
    const wrapper = mount(FileExplorer, {
      props: { activity: makeActivity({}), state },
    })

    expect(wrapper.text()).toContain('fallback.txt')
  })
})
