import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSettingsStore } from './settings.store'

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

describe('useSettingsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
    document.documentElement.classList.remove('dark')
  })

  it('defaults to system theme', () => {
    const store = useSettingsStore()
    expect(store.theme).toBe('system')
  })

  it('persists theme to localStorage', () => {
    const store = useSettingsStore()
    store.setTheme('dark')
    expect(localStorageMock.getItem('theme')).toBe('dark')
    expect(store.theme).toBe('dark')
  })

  it('applies dark class when theme is dark', () => {
    const store = useSettingsStore()
    store.setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('removes dark class when theme is light', () => {
    document.documentElement.classList.add('dark')
    const store = useSettingsStore()
    store.setTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('reads initial theme from localStorage', () => {
    localStorageMock.setItem('theme', 'dark')
    const store = useSettingsStore()
    expect(store.theme).toBe('dark')
  })
})
