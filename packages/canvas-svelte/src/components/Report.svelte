<!--
  Report canvas component — Svelte 5 variant.
  Props schema: forge/templates/_shared/canvas-components/Report.props.schema.json
-->
<script lang="ts">
  import { marked } from 'marked'
  import DOMPurify from 'dompurify'

  interface Props {
    title?: string
    markdown: string
  }

  let { title, markdown }: Props = $props()

  let html = $derived.by(() => {
    const rawHtml = marked.parse(markdown, { async: false }) as string
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

<article class="forge-canvas-report">
  {#if title}
    <header class="forge-canvas-report__header">
      <h2>{title}</h2>
    </header>
  {/if}
  <div class="forge-canvas-report__body">{@html html}</div>
</article>

<style>
  .forge-canvas-report { padding: 1rem 1.5rem; background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; }
  .forge-canvas-report__header h2 { margin: 0 0 1rem 0; font-size: 1.25rem; font-weight: 600; }
  .forge-canvas-report__body :global(h1),
  .forge-canvas-report__body :global(h2),
  .forge-canvas-report__body :global(h3) { margin: 1rem 0 0.5rem; font-weight: 600; }
  .forge-canvas-report__body :global(p) { margin: 0 0 0.75rem; line-height: 1.6; }
  .forge-canvas-report__body :global(pre) { padding: 0.75rem; background: var(--fc-muted, #f3f4f6); border-radius: 0.375rem; overflow-x: auto; font-family: ui-monospace, monospace; font-size: 0.875rem; }
  .forge-canvas-report__body :global(code) { font-family: ui-monospace, monospace; font-size: 0.875rem; padding: 0.1rem 0.3rem; background: var(--fc-muted, #f3f4f6); border-radius: 0.25rem; }
  .forge-canvas-report__body :global(pre code) { padding: 0; background: transparent; }
  .forge-canvas-report__body :global(ul),
  .forge-canvas-report__body :global(ol) { margin: 0 0 0.75rem; padding-left: 1.5rem; }
  .forge-canvas-report__body :global(a) { color: var(--fc-primary, #2563eb); text-decoration: underline; }
  .forge-canvas-report__body :global(blockquote) { margin: 0.75rem 0; padding: 0.5rem 1rem; border-left: 3px solid var(--fc-primary, #2563eb); background: var(--fc-muted, #f3f4f6); }
</style>
