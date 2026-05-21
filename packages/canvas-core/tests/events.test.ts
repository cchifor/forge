/**
 * Frame parser fuzz + happy path.
 *
 * The parser is the only place tolerant input meets typed output; tests
 * concentrate on its defensive coercion so the reducer can assume
 * well-shaped events.
 */

import { describe, expect, it } from 'vitest'
import { parseEvent } from '../src/index.js'

describe('parseEvent — happy path', () => {
  it('parses RUN_STARTED', () => {
    expect(parseEvent({ type: 'RUN_STARTED' })).toEqual({ type: 'RUN_STARTED' })
  })

  it('parses TEXT_MESSAGE_CONTENT with delta', () => {
    expect(
      parseEvent({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: 'hi' }),
    ).toEqual({
      type: 'TEXT_MESSAGE_CONTENT',
      messageId: 'm1',
      delta: 'hi',
    })
  })

  it('parses MESSAGES_SNAPSHOT, filtering non-object entries', () => {
    const event = parseEvent({
      type: 'MESSAGES_SNAPSHOT',
      messages: [
        { id: 'm1', role: 'user', content: 'hi' },
        'not-an-object',
        null,
        ['nope'],
      ],
    })
    expect(event.type).toBe('MESSAGES_SNAPSHOT')
    if (event.type !== 'MESSAGES_SNAPSHOT') throw new Error('type narrowing')
    expect(event.messages).toHaveLength(1)
  })

  it('parses STATE_DELTA, filtering non-object ops', () => {
    const event = parseEvent({
      type: 'STATE_DELTA',
      delta: [
        { op: 'replace', path: '/x', value: 1 },
        'malformed',
        null,
      ],
    })
    if (event.type !== 'STATE_DELTA') throw new Error('type narrowing')
    expect(event.delta).toHaveLength(1)
  })
})

describe('parseEvent — defensive coercion', () => {
  it('coerces missing strings to ""', () => {
    const event = parseEvent({ type: 'RUN_ERROR' })
    if (event.type !== 'RUN_ERROR') throw new Error('type narrowing')
    expect(event.message).toBe('')
  })

  it('defaults missing role to assistant', () => {
    const event = parseEvent({ type: 'TEXT_MESSAGE_START', messageId: 'm1' })
    if (event.type !== 'TEXT_MESSAGE_START') throw new Error('type narrowing')
    expect(event.role).toBe('assistant')
  })

  it('handles missing MESSAGES_SNAPSHOT.messages', () => {
    const event = parseEvent({ type: 'MESSAGES_SNAPSHOT' })
    if (event.type !== 'MESSAGES_SNAPSHOT') throw new Error('type narrowing')
    expect(event.messages).toEqual([])
  })

  it('returns UNKNOWN for unrecognised types', () => {
    const event = parseEvent({ type: 'FUTURE_EVENT_42', payload: { x: 1 } })
    expect(event.type).toBe('UNKNOWN')
    if (event.type !== 'UNKNOWN') throw new Error('type narrowing')
    expect(event.rawType).toBe('FUTURE_EVENT_42')
  })

  it('returns UNKNOWN for missing type field', () => {
    const event = parseEvent({ messageId: 'm1' })
    expect(event.type).toBe('UNKNOWN')
  })
})
