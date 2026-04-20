<!--
  DataTable canvas component — Svelte 5 variant.
-->
<script lang="ts">
  interface Column {
    key: string
    label: string
    sortable?: boolean
  }

  interface Props {
    columns: Column[]
    rows: Record<string, unknown>[]
    pageSize?: number
  }

  let { columns, rows, pageSize = 25 }: Props = $props()

  let sortKey = $state<string | null>(null)
  let sortDir = $state<'asc' | 'desc'>('asc')
  let page = $state(0)

  function toggleSort(column: Column) {
    if (!column.sortable) return
    if (sortKey === column.key) {
      sortDir = sortDir === 'asc' ? 'desc' : 'asc'
    } else {
      sortKey = column.key
      sortDir = 'asc'
    }
  }

  let sortedRows = $derived.by(() => {
    const out = [...rows]
    if (sortKey) {
      const key = sortKey
      out.sort((a, b) => {
        const av = a[key]
        const bv = b[key]
        if (av == null) return 1
        if (bv == null) return -1
        if (av < bv) return sortDir === 'asc' ? -1 : 1
        if (av > bv) return sortDir === 'asc' ? 1 : -1
        return 0
      })
    }
    return out
  })

  let totalPages = $derived(Math.max(1, Math.ceil(sortedRows.length / pageSize)))
  let pagedRows = $derived(sortedRows.slice(page * pageSize, (page + 1) * pageSize))

  function goTo(p: number) {
    page = Math.max(0, Math.min(totalPages - 1, p))
  }

  function formatCell(value: unknown): string {
    if (value === null || value === undefined) return ''
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
  }
</script>

<div class="forge-canvas-table">
  <table>
    <thead>
      <tr>
        {#each columns as col (col.key)}
          <th class:is-sortable={col.sortable} onclick={() => toggleSort(col)}>
            {col.label}
            {#if col.sortable}
              <span class="forge-canvas-table__sort" data-dir={sortKey === col.key ? sortDir : ''}>
                {sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
              </span>
            {/if}
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each pagedRows as row, i (i)}
        <tr>
          {#each columns as col (col.key)}
            <td>{formatCell(row[col.key])}</td>
          {/each}
        </tr>
      {:else}
        <tr>
          <td class="forge-canvas-table__empty" colspan={columns.length}>No rows.</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if totalPages > 1}
    <footer class="forge-canvas-table__footer">
      <button type="button" disabled={page === 0} onclick={() => goTo(page - 1)}>← Prev</button>
      <span>Page {page + 1} / {totalPages}</span>
      <button type="button" disabled={page >= totalPages - 1} onclick={() => goTo(page + 1)}>Next →</button>
    </footer>
  {/if}
</div>

<style>
  .forge-canvas-table { background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; overflow: hidden; }
  table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  th, td { padding: 0.625rem 0.75rem; text-align: left; border-bottom: 1px solid var(--fc-border, #e5e7eb); }
  th { background: var(--fc-muted, #f9fafb); font-weight: 600; user-select: none; }
  th.is-sortable { cursor: pointer; }
  th.is-sortable:hover { background: #f3f4f6; }
  .forge-canvas-table__sort { margin-left: 0.25rem; font-size: 0.75rem; color: #9ca3af; }
  .forge-canvas-table__sort[data-dir] { color: var(--fc-primary, #2563eb); }
  .forge-canvas-table__empty { text-align: center; color: #6b7280; padding: 2rem; }
  .forge-canvas-table__footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.5rem 0.75rem; background: var(--fc-muted, #f9fafb); border-top: 1px solid var(--fc-border, #e5e7eb); font-size: 0.8rem; }
  .forge-canvas-table__footer button { padding: 0.25rem 0.625rem; border: 1px solid var(--fc-border, #e5e7eb); background: var(--fc-surface, #fff); border-radius: 0.25rem; cursor: pointer; }
  .forge-canvas-table__footer button:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
