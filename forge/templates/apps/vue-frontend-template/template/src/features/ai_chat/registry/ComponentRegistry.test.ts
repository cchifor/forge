import { describe, it, expect } from 'vitest'
import { ComponentRegistry, type ComponentEntry } from './ComponentRegistry'

const stub = (name: string): ComponentEntry => ({
  component: { name } as ComponentEntry['component'],
  label: name,
})

describe('ComponentRegistry', () => {
  it('register + resolve returns the registered entry', () => {
    const registry = new ComponentRegistry()
    const entry = stub('Foo')
    registry.register('foo', entry)
    expect(registry.resolve('foo')).toBe(entry)
  })

  it('resolve falls back to the "fallback" entry for unknown types', () => {
    const registry = new ComponentRegistry()
    const fallback = stub('Fallback')
    registry.register('fallback', fallback)
    expect(registry.resolve('does_not_exist')).toBe(fallback)
  })

  it('resolve prefers an exact match over the fallback', () => {
    const registry = new ComponentRegistry()
    const fallback = stub('Fallback')
    const exact = stub('Exact')
    registry.register('fallback', fallback)
    registry.register('exact', exact)
    expect(registry.resolve('exact')).toBe(exact)
  })

  it('has reports membership correctly', () => {
    const registry = new ComponentRegistry()
    registry.register('foo', stub('Foo'))
    expect(registry.has('foo')).toBe(true)
    expect(registry.has('bar')).toBe(false)
  })

  it('entries iterates over all registered entries', () => {
    const registry = new ComponentRegistry()
    const a = stub('A')
    const b = stub('B')
    registry.register('a', a)
    registry.register('b', b)
    const collected = new Map(registry.entries())
    expect(collected.size).toBe(2)
    expect(collected.get('a')).toBe(a)
    expect(collected.get('b')).toBe(b)
  })

  it('register overwrites an existing entry for the same activity type', () => {
    const registry = new ComponentRegistry()
    const first = stub('First')
    const second = stub('Second')
    registry.register('x', first)
    registry.register('x', second)
    expect(registry.resolve('x')).toBe(second)
  })
})
