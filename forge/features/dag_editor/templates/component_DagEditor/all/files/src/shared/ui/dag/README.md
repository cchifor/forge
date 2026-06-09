# DAG editor

A generic directed-acyclic-graph canvas: a [Vue Flow](https://vueflow.dev)
viewport with [dagre](https://github.com/dagrejs/dagre) auto-layout. Extracted
to be model-agnostic — it knows nothing about workflows or any domain type; you
feed it a plain node/edge shape and it lays out + renders the graph.

## What ships

- `useDagLayout.ts` — `layoutDag(nodes, edges, options)`, a pure function that
  assigns dagre positions and returns Vue Flow `Node[]` / `Edge[]`. Direction
  `TB` (default) or `LR`.
- `DagEditor.vue` — the canvas: lays the graph out, renders it with Vue Flow +
  Background / Controls / MiniMap, fits the view on load and on change.
- `DagNode.vue` — the default node card (label + optional sublabel + handles).

## Usage

It's opt-in — selected via `components=["DagEditor"]`. `.vue` files can't be
auto-wired, so import it where you need it:

```vue
<script setup lang="ts">
import { DagEditor, type DagNodeInput, type DagEdgeInput } from '@/shared/ui/dag'

const nodes: DagNodeInput[] = [
  { id: 'a', label: 'Extract' },
  { id: 'b', label: 'Transform', sublabel: 'normalize' },
  { id: 'c', label: 'Load' },
]
const edges: DagEdgeInput[] = [
  { source: 'a', target: 'b' },
  { source: 'b', target: 'c' },
]
</script>

<template>
  <div class="h-[500px]">
    <DagEditor :nodes="nodes" :edges="edges" direction="TB" @node-click="(id) => console.log(id)" />
  </div>
</template>
```

Custom node bodies via the scoped `#node` slot (falls back to `DagNode`):

```vue
<DagEditor :nodes="nodes" :edges="edges">
  <template #node="{ node }">
    <MyNode :id="node.id" :data="node.data" :selected="node.selected" />
  </template>
</DagEditor>
```

## Dependencies

Selecting this component adds `@vue-flow/{core,background,controls,minimap}` +
`dagre` (and `@types/dagre`) to the generated app's `package.json` — gated so a
project that doesn't use the component carries none of them.
