<!--
  WorkflowDiagram — simple DAG layout of steps with status indicators.

  Layout: linear top-to-bottom, assigns each node a row by its
  topological depth and a column by its order within that depth. SVG
  arrows between nodes use straight-line routing — fine for the typical
  agent-workflow case of 5-15 nodes. More sophisticated layout (dagre,
  elk) stays out of scope to keep the component bundle tiny.

  Props schema: forge/templates/_shared/canvas-components/WorkflowDiagram.props.schema.json
-->
<script setup lang="ts">
import { computed } from 'vue'

interface Node {
  id: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'error' | 'skipped'
}

interface Edge {
  from: string
  to: string
}

interface Props {
  nodes: Node[]
  edges: Edge[]
}

const props = defineProps<Props>()

const NODE_W = 160
const NODE_H = 52
const H_GAP = 32
const V_GAP = 48

const layout = computed(() => {
  const depth = new Map<string, number>()
  const incoming = new Map<string, number>()
  for (const n of props.nodes) incoming.set(n.id, 0)
  for (const e of props.edges) incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1)
  const queue = props.nodes.filter((n) => (incoming.get(n.id) ?? 0) === 0).map((n) => n.id)
  for (const id of queue) depth.set(id, 0)
  while (queue.length) {
    const id = queue.shift()!
    for (const e of props.edges) {
      if (e.from !== id) continue
      const next = (depth.get(id) ?? 0) + 1
      if ((depth.get(e.to) ?? -1) < next) depth.set(e.to, next)
      incoming.set(e.to, (incoming.get(e.to) ?? 0) - 1)
      if ((incoming.get(e.to) ?? 0) === 0) queue.push(e.to)
    }
  }

  const byDepth = new Map<number, string[]>()
  for (const n of props.nodes) {
    const d = depth.get(n.id) ?? 0
    if (!byDepth.has(d)) byDepth.set(d, [])
    byDepth.get(d)!.push(n.id)
  }

  const positions = new Map<string, { x: number; y: number }>()
  const maxCols = Math.max(...Array.from(byDepth.values()).map((a: string[]) => a.length), 1)
  for (const [d, ids] of byDepth) {
    const rowW = ids.length * NODE_W + (ids.length - 1) * H_GAP
    const startX = ((maxCols * NODE_W + (maxCols - 1) * H_GAP) - rowW) / 2
    ids.forEach((id, i) => {
      positions.set(id, {
        x: startX + i * (NODE_W + H_GAP),
        y: d * (NODE_H + V_GAP),
      })
    })
  }

  const width = maxCols * NODE_W + (maxCols - 1) * H_GAP
  const height = ((byDepth.size || 1) - 1) * (NODE_H + V_GAP) + NODE_H
  return { positions, width, height }
})

function statusClass(status: Node['status']): string {
  return `forge-canvas-wf__node--${status}`
}

function statusIcon(status: Node['status']): string {
  return { pending: '○', running: '◐', completed: '●', error: '✕', skipped: '↳' }[status]
}
</script>

<template>
  <div class="forge-canvas-wf">
    <svg
      :viewBox="`0 0 ${layout.width} ${layout.height}`"
      :style="{ width: '100%', height: `${layout.height}px`, maxHeight: '600px' }"
    >
      <defs>
        <marker id="fcwf-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--fc-muted-fg, #9ca3af)" />
        </marker>
      </defs>
      <g>
        <line
          v-for="(edge, i) in props.edges"
          :key="i"
          :x1="(layout.positions.get(edge.from)?.x ?? 0) + NODE_W / 2"
          :y1="(layout.positions.get(edge.from)?.y ?? 0) + NODE_H"
          :x2="(layout.positions.get(edge.to)?.x ?? 0) + NODE_W / 2"
          :y2="layout.positions.get(edge.to)?.y ?? 0"
          stroke="var(--fc-muted-fg, #9ca3af)"
          stroke-width="1.5"
          marker-end="url(#fcwf-arrow)"
        />
      </g>
      <g>
        <g
          v-for="node in props.nodes"
          :key="node.id"
          :transform="`translate(${layout.positions.get(node.id)?.x ?? 0}, ${layout.positions.get(node.id)?.y ?? 0})`"
        >
          <rect
            :class="['forge-canvas-wf__node', statusClass(node.status)]"
            :width="NODE_W"
            :height="NODE_H"
            rx="8"
            ry="8"
          />
          <text
            :x="NODE_W / 2"
            :y="NODE_H / 2 + 5"
            text-anchor="middle"
            class="forge-canvas-wf__label"
          >
            {{ statusIcon(node.status) }} {{ node.label }}
          </text>
        </g>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.forge-canvas-wf { padding: 1rem; background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; overflow: auto; }
.forge-canvas-wf__node { stroke-width: 1.5; }
.forge-canvas-wf__node--pending { fill: #f3f4f6; stroke: #9ca3af; }
.forge-canvas-wf__node--running { fill: #fef3c7; stroke: #d97706; }
.forge-canvas-wf__node--completed { fill: #dcfce7; stroke: #16a34a; }
.forge-canvas-wf__node--error { fill: #fee2e2; stroke: #dc2626; }
.forge-canvas-wf__node--skipped { fill: #e5e7eb; stroke: #6b7280; }
.forge-canvas-wf__label { font-family: inherit; font-size: 13px; fill: #111827; pointer-events: none; }
</style>
