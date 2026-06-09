import { describe, it, expect } from 'vitest'
import { Position } from '@vue-flow/core'

import { layoutDag, type DagEdgeInput, type DagNodeInput } from './useDagLayout'

const NODES: DagNodeInput[] = [
  { id: 'a', label: 'Extract' },
  { id: 'b' }, // label defaults to id
  { id: 'c', label: 'Load', data: { kind: 'sink' } },
]
const EDGES: DagEdgeInput[] = [
  { source: 'a', target: 'b' },
  { source: 'b', target: 'c' },
]

describe('layoutDag', () => {
  it('returns one positioned node per input and derives flow edges', () => {
    const { nodes, edges } = layoutDag(NODES, EDGES)
    expect(nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'c'])
    // dagre assigned real coordinates (not all zero).
    expect(nodes.some((n) => n.position.x !== 0 || n.position.y !== 0)).toBe(true)
    expect(edges).toHaveLength(2)
    expect(edges.map((e) => e.id).sort()).toEqual(['a->b', 'b->c'])
    expect(edges.every((e) => e.type === 'smoothstep')).toBe(true)
  })

  it('defaults the label to the id and passes data through', () => {
    const { nodes } = layoutDag(NODES, EDGES)
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
    expect(byId.a.data?.label).toBe('Extract')
    expect(byId.b.data?.label).toBe('b')
    expect(byId.c.data?.kind).toBe('sink')
    expect(byId.a.type).toBe('dagNode')
  })

  it('orients handles per direction (TB = top/bottom, LR = left/right)', () => {
    const tb = layoutDag(NODES, EDGES, { direction: 'TB' }).nodes[0]
    expect(tb.sourcePosition).toBe(Position.Bottom)
    expect(tb.targetPosition).toBe(Position.Top)
    const lr = layoutDag(NODES, EDGES, { direction: 'LR' }).nodes[0]
    expect(lr.sourcePosition).toBe(Position.Right)
    expect(lr.targetPosition).toBe(Position.Left)
  })

  it('drops edges whose endpoints are not both present (no phantom nodes)', () => {
    const { nodes, edges } = layoutDag(NODES, [
      ...EDGES,
      { source: 'a', target: 'ghost' },
      { source: 'nowhere', target: 'c' },
    ])
    expect(nodes).toHaveLength(3)
    expect(edges).toHaveLength(2) // the two dangling edges are filtered
  })

  it('honours a custom nodeType', () => {
    const { nodes } = layoutDag(NODES, EDGES, { nodeType: 'customNode' })
    expect(nodes.every((n) => n.type === 'customNode')).toBe(true)
  })
})
