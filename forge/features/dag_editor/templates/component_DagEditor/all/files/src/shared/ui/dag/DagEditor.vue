<script setup lang="ts">
/**
 * Generic DAG editor/viewer — a Vue Flow canvas with dagre auto-layout.
 *
 * Pass a generic ``nodes`` + ``edges`` shape; the component lays them out with
 * dagre (TB or LR), renders them via Vue Flow with Background / Controls /
 * MiniMap, and fits the view on load + whenever the graph changes. It is
 * model-agnostic: no store, no domain types. Selection + node clicks are
 * surfaced via Vue Flow's built-in selection and the ``node-click`` emit.
 *
 * Customise node rendering with the scoped ``#node`` slot (falls back to the
 * bundled ``DagNode``):
 *
 *   <DagEditor :nodes="nodes" :edges="edges">
 *     <template #node="{ node }"><MyNode :data="node.data" /></template>
 *   </DagEditor>
 */
import { computed, nextTick, watch } from 'vue'
import { VueFlow, useVueFlow, type NodeMouseEvent } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

import DagNode from './DagNode.vue'
import {
  layoutDag,
  type DagEdgeInput,
  type DagNodeInput,
  type LayoutDirection,
} from './useDagLayout'

const props = withDefaults(
  defineProps<{
    nodes: DagNodeInput[]
    edges: DagEdgeInput[]
    direction?: LayoutDirection
    nodesDraggable?: boolean
    showMiniMap?: boolean
    showControls?: boolean
    showBackground?: boolean
    /** Auto fit-to-view on init + whenever the node set changes. */
    fitOnChange?: boolean
  }>(),
  {
    direction: 'TB',
    nodesDraggable: true,
    showMiniMap: true,
    showControls: true,
    showBackground: true,
    fitOnChange: true,
  },
)

const emit = defineEmits<{ 'node-click': [id: string] }>()

const nodeTypes = { dagNode: DagNode } as Record<string, unknown>
const flow = useVueFlow()

// Recompute the dagre layout only when the graph or direction changes — NOT on
// drag or selection (Vue Flow owns that transient state internally), so user
// interactions don't snap back.
const laidOut = computed(() => layoutDag(props.nodes, props.edges, { direction: props.direction }))
const flowNodes = computed(() => laidOut.value.nodes)
const flowEdges = computed(() => laidOut.value.edges)

function onNodeClick(e: NodeMouseEvent): void {
  emit('node-click', e.node.id)
}

// Explicit fit (no `fit-view-on-init` — that gates canvas opacity and can flash
// on a populated load). Fit on the first measured-node batch, then on any later
// node-set change.
flow.onNodesInitialized(() => {
  if (props.fitOnChange) flow.fitView()
})
watch(
  () => flowNodes.value.map((n) => n.id).join(','),
  () => {
    if (props.fitOnChange) nextTick(() => flow.fitView())
  },
)
</script>

<template>
  <div class="relative h-full w-full min-h-[300px]" data-testid="dag-editor">
    <VueFlow
      :nodes="flowNodes"
      :edges="flowEdges"
      :node-types="nodeTypes"
      :default-edge-options="{ type: 'smoothstep' }"
      :nodes-draggable="props.nodesDraggable"
      :nodes-connectable="false"
      @node-click="onNodeClick"
    >
      <template #node-dagNode="nodeProps">
        <slot name="node" :node="nodeProps">
          <DagNode v-bind="nodeProps" />
        </slot>
      </template>

      <Background v-if="props.showBackground" pattern-color="#aaa" :gap="20" />
      <Controls v-if="props.showControls" />
      <MiniMap
        v-if="props.showMiniMap"
        pannable
        zoomable
        class="!left-1 !right-auto !bottom-1"
        :style="{
          backgroundColor: 'hsl(var(--background))',
          border: '1px solid hsl(var(--border))',
        }"
        node-color="hsl(var(--muted-foreground))"
        node-stroke-color="none"
        mask-color="hsl(var(--background) / 0.7)"
        mask-stroke-color="none"
      />
    </VueFlow>
  </div>
</template>
