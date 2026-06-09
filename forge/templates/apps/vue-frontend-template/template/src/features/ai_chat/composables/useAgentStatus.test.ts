import { describe, it, expect, beforeEach } from 'vitest'

import { useAgentStatus } from './useAgentStatus'

describe('useAgentStatus', () => {
  beforeEach(() => useAgentStatus().reset())

  it('starts idle', () => {
    expect(useAgentStatus().status.value).toBe('idle')
  })

  it('allows the run lifecycle idle → running → idle', () => {
    const s = useAgentStatus()
    expect(s.transition('running')).toBe(true)
    expect(s.status.value).toBe('running')
    expect(s.isBusy()).toBe(true)
    expect(s.transition('idle')).toBe(true)
    expect(s.status.value).toBe('idle')
  })

  it('rejects an illegal transition and stays put', () => {
    const s = useAgentStatus()
    // idle cannot jump straight to awaitingPrompt.
    expect(s.transition('awaitingPrompt')).toBe(false)
    expect(s.status.value).toBe('idle')
  })

  it('same-status transition is a no-op success (double-submit safety)', () => {
    const s = useAgentStatus()
    s.transition('running')
    expect(s.transition('running')).toBe(true)
    expect(s.status.value).toBe('running')
  })

  it('running → awaitingPrompt → running (answer) and isWaitingForUser', () => {
    const s = useAgentStatus()
    s.transition('running')
    expect(s.transition('awaitingPrompt')).toBe(true)
    expect(s.isWaitingForUser()).toBe(true)
    expect(s.isBusy()).toBe(false)
    expect(s.transition('running')).toBe(true)
  })

  it('error is reachable from running and recovers on a new run', () => {
    const s = useAgentStatus()
    s.transition('running')
    expect(s.transition('error')).toBe(true)
    expect(s.status.value).toBe('error')
    expect(s.transition('running')).toBe(true) // new message recovers
  })

  it('canTransitionTo reflects the adjacency rules', () => {
    const s = useAgentStatus()
    expect(s.canTransitionTo('running')).toBe(true)
    expect(s.canTransitionTo('awaitingApproval')).toBe(false) // not from idle
  })
})
