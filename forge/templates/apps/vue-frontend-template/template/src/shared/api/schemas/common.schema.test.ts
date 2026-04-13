import { describe, it, expect } from 'vitest'
import { z } from 'zod'
import { paginatedResponseSchema, apiErrorSchema } from '@/shared/api/schemas/common.schema'

describe('paginatedResponseSchema', () => {
  const stringSchema = paginatedResponseSchema(z.string())

  it('parses valid paginated data', () => {
    const result = stringSchema.parse({
      items: ['a', 'b', 'c'],
      total: 3,
      skip: 0,
      limit: 50,
      has_more: false,
    })
    expect(result.items).toEqual(['a', 'b', 'c'])
    expect(result.total).toBe(3)
    expect(result.skip).toBe(0)
    expect(result.limit).toBe(50)
    expect(result.has_more).toBe(false)
  })

  it('parses empty items array', () => {
    const result = stringSchema.parse({
      items: [],
      total: 0,
      skip: 0,
      limit: 50,
      has_more: false,
    })
    expect(result.items).toEqual([])
    expect(result.total).toBe(0)
  })

  it('validates item types against inner schema', () => {
    const numSchema = paginatedResponseSchema(z.number())
    const result = numSchema.parse({
      items: [1, 2, 3],
      total: 3,
      skip: 0,
      limit: 10,
      has_more: false,
    })
    expect(result.items).toEqual([1, 2, 3])
  })

  it('rejects items that do not match inner schema', () => {
    expect(() =>
      stringSchema.parse({
        items: [123],
        total: 1,
        skip: 0,
        limit: 50,
        has_more: false,
      }),
    ).toThrow()
  })

  it('rejects missing total field', () => {
    expect(() =>
      stringSchema.parse({
        items: [],
        skip: 0,
        limit: 50,
        has_more: false,
      }),
    ).toThrow()
  })

  it('rejects missing items field', () => {
    expect(() =>
      stringSchema.parse({
        total: 0,
        skip: 0,
        limit: 50,
        has_more: false,
      }),
    ).toThrow()
  })
})

describe('apiErrorSchema', () => {
  it('parses valid error object', () => {
    const result = apiErrorSchema.parse({
      message: 'Not found',
      type: 'NotFoundError',
      detail: { id: 42 },
    })
    expect(result.message).toBe('Not found')
    expect(result.type).toBe('NotFoundError')
    expect(result.detail).toEqual({ id: 42 })
  })

  it('parses error with null detail', () => {
    const result = apiErrorSchema.parse({
      message: 'Server error',
      type: 'ServerError',
      detail: null,
    })
    expect(result.detail).toBeNull()
  })

  it('parses error without detail field', () => {
    const result = apiErrorSchema.parse({
      message: 'Unauthorized',
      type: 'AuthError',
    })
    expect(result.detail).toBeUndefined()
  })

  it('rejects missing message', () => {
    expect(() =>
      apiErrorSchema.parse({ type: 'SomeError' }),
    ).toThrow()
  })

  it('rejects missing type', () => {
    expect(() =>
      apiErrorSchema.parse({ message: 'error' }),
    ).toThrow()
  })
})
