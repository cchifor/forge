<!--
  Approval dialog for MCP tool calls (Svelte 5 scaffold, Phase 3.4).
-->
<script lang="ts">
  interface Props {
    toolName: string
    server: string
    inputPreview: string
    defaultMode: 'auto' | 'prompt-once' | 'prompt-every'
    onapprove: (remember: boolean) => void
    ondeny: () => void
  }

  let { toolName, server, inputPreview, defaultMode, onapprove, ondeny }: Props = $props()
  let remember = $state(defaultMode !== 'prompt-every')
</script>

<div class="approval-dialog" role="dialog" aria-modal="true">
  <h3>Approve tool call?</h3>
  <p><strong>{server} · {toolName}</strong></p>
  <pre class="input-preview">{inputPreview}</pre>
  <label>
    <input type="checkbox" bind:checked={remember} />
    Remember this choice for this session
  </label>
  <footer>
    <button type="button" class="deny" onclick={() => ondeny()}>Deny</button>
    <button type="button" class="approve" onclick={() => onapprove(remember)}>Approve</button>
  </footer>
</div>

<style>
  .approval-dialog { padding: 1rem; background: var(--surface, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 0.5rem; max-width: 32rem; }
  .input-preview { padding: 0.5rem; background: var(--muted, #f3f4f6); border-radius: 0.25rem; font-family: ui-monospace, monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-word; max-height: 12rem; overflow: auto; }
  footer { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
  .approve { background: var(--primary, #2563eb); color: white; padding: 0.5rem 1rem; border-radius: 0.25rem; border: none; }
  .deny { background: transparent; border: 1px solid var(--border, #e5e7eb); padding: 0.5rem 1rem; border-radius: 0.25rem; }
</style>
