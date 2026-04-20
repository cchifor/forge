<!--
  Report — canvas component for rendering Markdown content with an
  optional title header. Shadcn-flavored card styling matching the other
  canvas components.

  Props schema: forge/templates/_shared/canvas-components/Report.props.schema.json
  Runtime lint via useCanvasRegistry(...).lintAndResolve.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

interface Props {
  title?: string
  markdown: string
}

const props = defineProps<Props>()

const renderedHtml = computed(() => {
  const rawHtml = marked.parse(props.markdown, { async: false }) as string
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'br', 'strong', 'em', 'code', 'pre',
      'ul', 'ol', 'li', 'blockquote',
      'a', 'img',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'hr',
    ],
    ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class'],
  })
})
</script>

<template>
  <article class="forge-canvas-report">
    <header v-if="props.title" class="forge-canvas-report__header">
      <h2>{{ props.title }}</h2>
    </header>
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div class="forge-canvas-report__body" v-html="renderedHtml" />
  </article>
</template>

<style scoped>
.forge-canvas-report { padding: 1rem 1.5rem; background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; }
.forge-canvas-report__header h2 { margin: 0 0 1rem 0; font-size: 1.25rem; font-weight: 600; }
.forge-canvas-report__body :deep(h1),
.forge-canvas-report__body :deep(h2),
.forge-canvas-report__body :deep(h3) { margin: 1rem 0 0.5rem; font-weight: 600; }
.forge-canvas-report__body :deep(p) { margin: 0 0 0.75rem; line-height: 1.6; }
.forge-canvas-report__body :deep(pre) { padding: 0.75rem; background: var(--fc-muted, #f3f4f6); border-radius: 0.375rem; overflow-x: auto; font-family: ui-monospace, monospace; font-size: 0.875rem; }
.forge-canvas-report__body :deep(code) { font-family: ui-monospace, monospace; font-size: 0.875rem; padding: 0.1rem 0.3rem; background: var(--fc-muted, #f3f4f6); border-radius: 0.25rem; }
.forge-canvas-report__body :deep(pre code) { padding: 0; background: transparent; }
.forge-canvas-report__body :deep(ul),
.forge-canvas-report__body :deep(ol) { margin: 0 0 0.75rem; padding-left: 1.5rem; }
.forge-canvas-report__body :deep(a) { color: var(--fc-primary, #2563eb); text-decoration: underline; }
.forge-canvas-report__body :deep(blockquote) { margin: 0.75rem 0; padding: 0.5rem 1rem; border-left: 3px solid var(--fc-primary, #2563eb); background: var(--fc-muted, #f3f4f6); }
</style>
