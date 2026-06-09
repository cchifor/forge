<script setup lang="ts" generic="T">
/**
 * AsyncStateBlock — canonical orchestrator for the
 *   loading -> error -> empty -> success
 * lifecycle of any async data surface (TanStack Query, fetch, etc.).
 *
 * Owns the branch ladder once so the loading skeleton, the error block, and
 * the empty block render identically everywhere instead of each view
 * hand-rolling its own `if (isPending) … else if (isError) …` variant.
 *
 * Each branch is overridable via a named slot:
 *  - `#loading`  — replace the default skeleton stack.
 *  - `#error`    — replace the default error block (gets `{ error, retry }`).
 *  - `#empty`    — replace the default empty block.
 *  - default     — the success branch; receives `{ data: T }`.
 */
import { computed, type Component } from 'vue'
import { AlertCircle, Inbox } from 'lucide-vue-next'
import FeatureEmptyState from './FeatureEmptyState.vue'

type State = 'loading' | 'error' | 'empty' | 'success'

interface Props {
  isLoading: boolean
  isError: boolean
  error?: unknown
  data?: T | null
  /** Optional emptiness predicate; defaults to `data == null`. */
  isEmpty?: (data: T) => boolean
  emptyTitle?: string
  emptyBody?: string
  emptyIcon?: Component
  emptyPrimaryAction?: { label: string; icon?: Component; onClick: () => void }
  emptySecondaryAction?: { label: string; icon?: Component; onClick: () => void }
  onRetry?: () => void
}

const props = defineProps<Props>()

const state = computed<State>(() => {
  if (props.isLoading) return 'loading'
  if (props.isError) return 'error'
  if (props.data == null || (props.isEmpty?.(props.data) ?? false))
    return 'empty'
  return 'success'
})

const errorMessage = computed(() => {
  if (!props.error) return 'Something went wrong'
  if (props.error instanceof Error) return props.error.message
  return String(props.error)
})

const retryAction = computed(() =>
  props.onRetry ? { label: 'Try again', onClick: props.onRetry } : undefined,
)
</script>

<template>
  <!-- Loading: skeleton slot or default skeleton stack -->
  <div v-if="state === 'loading'" data-testid="async-state-loading">
    <slot name="loading">
      <div class="space-y-2">
        <div class="h-4 w-full animate-pulse rounded bg-muted" />
        <div class="h-4 w-3/4 animate-pulse rounded bg-muted" />
        <div class="h-4 w-1/2 animate-pulse rounded bg-muted" />
      </div>
    </slot>
  </div>

  <!-- Error: slot or default FeatureEmptyState with retry -->
  <div v-else-if="state === 'error'" data-testid="async-state-error">
    <slot name="error" :error="error" :retry="onRetry">
      <FeatureEmptyState
        :icon="AlertCircle"
        title="Failed to load"
        :body="errorMessage"
        :primary-action="retryAction"
      />
    </slot>
  </div>

  <!-- Empty: slot or default FeatureEmptyState -->
  <div v-else-if="state === 'empty'" data-testid="async-state-empty">
    <slot name="empty">
      <FeatureEmptyState
        :icon="emptyIcon ?? Inbox"
        :title="emptyTitle ?? 'Nothing here yet'"
        :body="emptyBody ?? ''"
        :primary-action="emptyPrimaryAction"
        :secondary-action="emptySecondaryAction"
      />
    </slot>
  </div>

  <!-- Success: default slot with the (now guaranteed non-null) data -->
  <slot v-else :data="(data as T)" />
</template>
