<!--
  DynamicForm canvas component — Svelte 5 variant.
-->
<script lang="ts">
  interface Field {
    name: string
    label: string
    type: 'text' | 'number' | 'password' | 'email' | 'select' | 'checkbox' | 'textarea'
    required?: boolean
    default?: unknown
    options?: string[]
    description?: string
  }

  interface Props {
    title?: string
    fields: Field[]
    submitLabel?: string
    cancelLabel?: string
    onsubmit?: (values: Record<string, unknown>) => void
    oncancel?: () => void
  }

  let { title, fields, submitLabel, cancelLabel, onsubmit, oncancel }: Props = $props()

  function _defaultFor(type: Field['type']): unknown {
    if (type === 'checkbox') return false
    if (type === 'number') return 0
    return ''
  }

  let values = $state<Record<string, unknown>>(
    Object.fromEntries(fields.map((f) => [f.name, f.default ?? _defaultFor(f.type)])),
  )

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault()
    onsubmit?.({ ...values })
  }
</script>

<form class="forge-canvas-form" onsubmit={handleSubmit}>
  {#if title}
    <header class="forge-canvas-form__header"><h3>{title}</h3></header>
  {/if}
  {#each fields as field (field.name)}
    <div class="forge-canvas-form__field">
      <label for="dform-{field.name}">
        {field.label}
        {#if field.required}<span class="forge-canvas-form__required">*</span>{/if}
      </label>
      {#if field.type === 'text' || field.type === 'password' || field.type === 'email'}
        <input
          id="dform-{field.name}"
          type={field.type}
          name={field.name}
          required={field.required ?? false}
          bind:value={values[field.name]}
        />
      {:else if field.type === 'number'}
        <input
          id="dform-{field.name}"
          type="number"
          name={field.name}
          required={field.required ?? false}
          bind:value={values[field.name]}
        />
      {:else if field.type === 'textarea'}
        <textarea
          id="dform-{field.name}"
          name={field.name}
          rows="4"
          required={field.required ?? false}
          bind:value={values[field.name]}
        ></textarea>
      {:else if field.type === 'select'}
        <select
          id="dform-{field.name}"
          name={field.name}
          required={field.required ?? false}
          bind:value={values[field.name]}
        >
          {#each (field.options ?? []) as opt (opt)}
            <option value={opt}>{opt}</option>
          {/each}
        </select>
      {:else if field.type === 'checkbox'}
        <label class="forge-canvas-form__checkbox">
          <input
            id="dform-{field.name}"
            type="checkbox"
            name={field.name}
            bind:checked={values[field.name]}
          />
          <span>{field.description || field.label}</span>
        </label>
      {/if}
      {#if field.description && field.type !== 'checkbox'}
        <p class="forge-canvas-form__help">{field.description}</p>
      {/if}
    </div>
  {/each}
  <footer class="forge-canvas-form__footer">
    <button type="button" class="forge-canvas-form__cancel" onclick={() => oncancel?.()}>
      {cancelLabel || 'Cancel'}
    </button>
    <button type="submit" class="forge-canvas-form__submit">
      {submitLabel || 'Submit'}
    </button>
  </footer>
</form>

<style>
  .forge-canvas-form { display: flex; flex-direction: column; gap: 1rem; padding: 1rem 1.25rem; background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; }
  .forge-canvas-form__header h3 { margin: 0 0 0.5rem 0; font-size: 1.1rem; }
  .forge-canvas-form__field { display: flex; flex-direction: column; gap: 0.25rem; }
  .forge-canvas-form__field label { font-weight: 500; font-size: 0.875rem; }
  .forge-canvas-form__required { color: var(--fc-destructive, #dc2626); margin-left: 0.125rem; }
  .forge-canvas-form__field input, .forge-canvas-form__field textarea, .forge-canvas-form__field select { padding: 0.5rem 0.625rem; border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.375rem; font-size: 0.875rem; font-family: inherit; }
  .forge-canvas-form__field input:focus, .forge-canvas-form__field textarea:focus, .forge-canvas-form__field select:focus { outline: 2px solid var(--fc-primary, #2563eb); outline-offset: -1px; }
  .forge-canvas-form__checkbox { flex-direction: row; align-items: center; gap: 0.5rem; }
  .forge-canvas-form__checkbox input { width: auto; }
  .forge-canvas-form__help { font-size: 0.75rem; color: #6b7280; margin: 0; }
  .forge-canvas-form__footer { display: flex; gap: 0.5rem; justify-content: flex-end; padding-top: 0.25rem; }
  .forge-canvas-form__submit { background: var(--fc-primary, #2563eb); color: white; padding: 0.5rem 1rem; border: none; border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
  .forge-canvas-form__cancel { background: transparent; padding: 0.5rem 1rem; border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
</style>
