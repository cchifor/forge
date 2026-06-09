<script setup lang="ts">
/**
 * Default Vue Flow node for the DAG canvas — a generic card showing a primary
 * ``label`` (falls back to the node id) and an optional ``sublabel``. Handles
 * follow the layout direction (``targetPosition`` / ``sourcePosition`` set by
 * ``layoutDag``). Selection ring is driven by Vue Flow's own ``selected``.
 *
 * Override the rendered body entirely via the editor's ``#node`` slot when a
 * consumer needs richer per-node content (status badges, icons, actions).
 */
import { Handle, Position, type NodeProps } from '@vue-flow/core'

interface DagNodeData {
  label?: string
  sublabel?: string | null
  [key: string]: unknown
}

const props = defineProps<NodeProps<DagNodeData>>()
</script>

<template>
  <div
    class="rounded-md border bg-card px-3 py-2 shadow-sm text-xs min-w-[180px]"
    :class="props.selected ? 'ring-2 ring-primary' : ''"
    :data-testid="`dag-node-${props.id}`"
  >
    <Handle :position="props.targetPosition ?? Position.Top" type="target" />
    <div class="font-medium font-mono truncate">
      {{ props.data.label ?? props.id }}
    </div>
    <div
      v-if="props.data.sublabel"
      class="mt-0.5 text-muted-foreground truncate"
    >
      {{ props.data.sublabel }}
    </div>
    <Handle :position="props.sourcePosition ?? Position.Bottom" type="source" />
  </div>
</template>

<style>
.vue-flow__handle {
  width: 8px;
  height: 8px;
  background: hsl(var(--muted-foreground) / 0.5);
}
</style>
