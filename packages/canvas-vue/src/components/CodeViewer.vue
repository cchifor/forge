<!--
  CodeViewer — syntax-highlighted code block with optional filename
  header + line numbers. Uses highlight.js so the bundle size is
  predictable (common + ~35 languages).

  Props schema: forge/templates/_shared/canvas-components/CodeViewer.props.schema.json
-->
<script setup lang="ts">
import { computed } from 'vue'
import hljs from 'highlight.js/lib/common'

interface Props {
  code: string
  language: string
  filename?: string
  showLineNumbers?: boolean
}

const props = defineProps<Props>()

const highlighted = computed(() => {
  try {
    const langOk = hljs.getLanguage(props.language) !== undefined
    const result = langOk
      ? hljs.highlight(props.code, { language: props.language, ignoreIllegals: true })
      : hljs.highlightAuto(props.code)
    return result.value
  } catch {
    // On unknown / failed highlight, fall back to plain text — users still
    // see their code even if the language is unsupported.
    return props.code
  }
})

const lines = computed(() =>
  props.showLineNumbers ? props.code.split('\n').map((_, i) => i + 1) : [],
)
</script>

<template>
  <figure class="forge-canvas-code">
    <figcaption v-if="props.filename" class="forge-canvas-code__header">
      <span>{{ props.filename }}</span>
      <span class="forge-canvas-code__lang">{{ props.language }}</span>
    </figcaption>
    <pre class="forge-canvas-code__body"><code
      v-if="props.showLineNumbers"
      class="forge-canvas-code__with-lines"
    ><span class="forge-canvas-code__lines"><span
      v-for="n in lines"
      :key="n"
      class="forge-canvas-code__line-num"
    >{{ n }}</span></span><span
      class="forge-canvas-code__code hljs"
      v-html="highlighted"
    /></code><code
      v-else
      class="forge-canvas-code__code hljs"
      v-html="highlighted"
    /></pre>
  </figure>
</template>

<style scoped>
.forge-canvas-code { margin: 0; background: var(--fc-muted, #f3f4f6); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; overflow: hidden; }
.forge-canvas-code__header { display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0.75rem; background: var(--fc-surface, #fff); border-bottom: 1px solid var(--fc-border, #e5e7eb); font-family: ui-monospace, monospace; font-size: 0.75rem; color: var(--fc-muted-fg, #6b7280); }
.forge-canvas-code__lang { text-transform: uppercase; letter-spacing: 0.05em; }
.forge-canvas-code__body { margin: 0; padding: 0.75rem 1rem; overflow-x: auto; }
.forge-canvas-code__with-lines { display: grid; grid-template-columns: auto 1fr; gap: 0.75rem; }
.forge-canvas-code__lines { display: flex; flex-direction: column; color: var(--fc-muted-fg, #9ca3af); user-select: none; text-align: right; }
.forge-canvas-code__line-num { font-family: ui-monospace, monospace; font-size: 0.85rem; line-height: 1.5; }
.forge-canvas-code__code { font-family: ui-monospace, monospace; font-size: 0.875rem; line-height: 1.5; }
:deep(.hljs-keyword), :deep(.hljs-selector-tag) { color: var(--fc-primary, #2563eb); font-weight: 600; }
:deep(.hljs-string), :deep(.hljs-attr) { color: #16a34a; }
:deep(.hljs-comment) { color: #6b7280; font-style: italic; }
:deep(.hljs-number) { color: #dc2626; }
</style>
