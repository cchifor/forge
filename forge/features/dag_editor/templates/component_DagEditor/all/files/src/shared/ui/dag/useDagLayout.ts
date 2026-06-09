/**
 * Dagre-backed auto-layout for the Vue Flow canvas.
 *
 * Pure function — given a generic node list + edge list (any DAG shape),
 * returns Vue Flow ``Node`` + ``Edge`` arrays with x/y positions assigned by
 * dagre. Callers layer their own per-node state on top via the node ``data``.
 *
 * Direction defaults to TB (top-down); LR is available for wide DAGs laid out
 * horizontally. The node ``type`` defaults to ``dagNode`` (the bundled
 * :file:`DagNode.vue`); override it to register a custom Vue Flow node type.
 */
import dagre from 'dagre'
import { Position, type Edge, type Node } from '@vue-flow/core'

export type LayoutDirection = 'TB' | 'LR'

/**
 * A node in the DAG. ``data`` is merged into the rendered Vue Flow node's
 * ``data`` so a custom node (via the editor's ``#node`` slot) can read
 * arbitrary fields. ``label`` defaults to ``id``.
 */
export interface DagNodeInput {
  id: string
  label?: string
  sublabel?: string | null
  data?: Record<string, unknown>
}

/** A directed edge ``source → target`` (both must be node ids). */
export interface DagEdgeInput {
  source: string
  target: string
}

export interface LayoutOptions {
  direction?: LayoutDirection
  nodeWidth?: number
  nodeHeight?: number
  rankSep?: number
  nodeSep?: number
  /** Vue Flow node ``type`` to assign (must match a registered nodeType). */
  nodeType?: string
}

const DEFAULTS: Required<LayoutOptions> = {
  direction: 'TB',
  nodeWidth: 200,
  nodeHeight: 80,
  rankSep: 80,
  nodeSep: 40,
  nodeType: 'dagNode',
}

export function layoutDag(
  nodes: DagNodeInput[],
  edges: DagEdgeInput[],
  options: LayoutOptions = {},
): { nodes: Node[]; edges: Edge[] } {
  const opts = { ...DEFAULTS, ...options }
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({
    rankdir: opts.direction,
    nodesep: opts.nodeSep,
    ranksep: opts.rankSep,
    marginx: 16,
    marginy: 16,
  })
  graph.setDefaultEdgeLabel(() => ({}))

  const ids = new Set(nodes.map((n) => n.id))
  for (const n of nodes) {
    graph.setNode(n.id, { width: opts.nodeWidth, height: opts.nodeHeight })
  }
  // Only wire edges whose endpoints both exist — a dangling edge would make
  // dagre create a phantom node and throw off the layout.
  const validEdges = edges.filter((e) => ids.has(e.source) && ids.has(e.target))
  for (const e of validEdges) graph.setEdge(e.source, e.target)

  dagre.layout(graph)

  const flowNodes: Node[] = nodes.map((n) => {
    const positioned = graph.node(n.id) as { x: number; y: number } | undefined
    return {
      id: n.id,
      type: opts.nodeType,
      position: positioned
        ? {
            x: positioned.x - opts.nodeWidth / 2,
            y: positioned.y - opts.nodeHeight / 2,
          }
        : { x: 0, y: 0 },
      data: { label: n.label ?? n.id, sublabel: n.sublabel ?? null, ...(n.data ?? {}) },
      sourcePosition: opts.direction === 'TB' ? Position.Bottom : Position.Right,
      targetPosition: opts.direction === 'TB' ? Position.Top : Position.Left,
    }
  })

  const flowEdges: Edge[] = validEdges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
  }))

  return { nodes: flowNodes, edges: flowEdges }
}
