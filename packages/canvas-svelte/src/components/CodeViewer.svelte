<!--
  CodeViewer canvas component — Svelte 5 variant.
-->
<script lang="ts">
  import hljs from 'highlight.js/lib/common'

  interface Props {
    code: string
    language: string
    filename?: string
    showLineNumbers?: boolean
  }

  let { code, language, filename, showLineNumbers = false }: Props = $props()

  let highlighted = $derived.by(() => {
    try {
      const langOk = hljs.getLanguage(language) !== undefined
      const result = langOk
        ? hljs.highlight(code, { language, ignoreIllegals: true })
        : hljs.highlightAuto(code)
      return result.value
    } catch {
      return code
    }
  })

  let lines = $derived(
    showLineNumbers ? code.split('\n').map((_, i) => i + 1) : [],
  )
</script>

<figure class="forge-canvas-code">
  {#if filename}
    <figcaption class="forge-canvas-code__header">
      <span>{filename}</span>
      <span class="forge-canvas-code__lang">{language}</span>
    </figcaption>
  {/if}
  <pre class="forge-canvas-code__body">{#if showLineNumbers}<code class="forge-canvas-code__with-lines"><span class="forge-canvas-code__lines">{#each lines as n (n)}<span class="forge-canvas-code__line-num">{n}</span>{/each}</span><span class="forge-canvas-code__code hljs">{@html highlighted}</span></code>{:else}<code class="forge-canvas-code__code hljs">{@html highlighted}</code>{/if}</pre>
</figure>

<style>
  .forge-canvas-code { margin: 0; background: var(--fc-muted, #f3f4f6); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; overflow: hidden; }
  .forge-canvas-code__header { display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0.75rem; background: var(--fc-surface, #fff); border-bottom: 1px solid var(--fc-border, #e5e7eb); font-family: ui-monospace, monospace; font-size: 0.75rem; color: var(--fc-muted-fg, #6b7280); }
  .forge-canvas-code__lang { text-transform: uppercase; letter-spacing: 0.05em; }
  .forge-canvas-code__body { margin: 0; padding: 0.75rem 1rem; overflow-x: auto; }
  .forge-canvas-code__with-lines { display: grid; grid-template-columns: auto 1fr; gap: 0.75rem; }
  .forge-canvas-code__lines { display: flex; flex-direction: column; color: var(--fc-muted-fg, #9ca3af); user-select: none; text-align: right; }
  .forge-canvas-code__line-num { font-family: ui-monospace, monospace; font-size: 0.85rem; line-height: 1.5; }
  .forge-canvas-code__code { font-family: ui-monospace, monospace; font-size: 0.875rem; line-height: 1.5; }
</style>
