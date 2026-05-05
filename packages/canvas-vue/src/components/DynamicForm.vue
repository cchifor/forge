<!--
  DynamicForm — renders a form from a JSON-Schema-like field list.
  Dispatches by type: text, number, password, email, select, checkbox, textarea.

  Props schema: forge/templates/_shared/canvas-components/DynamicForm.props.schema.json
-->
<script setup lang="ts">
import { reactive } from 'vue'

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
}

const props = defineProps<Props>()
const emit = defineEmits<{
  submit: [values: Record<string, unknown>]
  cancel: []
}>()

const values = reactive<Record<string, unknown>>(
  Object.fromEntries(props.fields.map((f) => [f.name, f.default ?? _defaultFor(f.type)])),
)

function _defaultFor(type: Field['type']): unknown {
  if (type === 'checkbox') return false
  if (type === 'number') return 0
  return ''
}

function onSubmit(e: Event) {
  e.preventDefault()
  emit('submit', { ...values })
}
</script>

<template>
  <form class="forge-canvas-form" @submit="onSubmit">
    <header v-if="props.title" class="forge-canvas-form__header">
      <h3>{{ props.title }}</h3>
    </header>
    <div v-for="field in props.fields" :key="field.name" class="forge-canvas-form__field">
      <label :for="`dform-${field.name}`">
        {{ field.label }}
        <span v-if="field.required" class="forge-canvas-form__required">*</span>
      </label>

      <input
        v-if="field.type === 'text' || field.type === 'password' || field.type === 'email'"
        :id="`dform-${field.name}`"
        :type="field.type"
        :name="field.name"
        :required="field.required"
        v-model="values[field.name] as any"
      />
      <input
        v-else-if="field.type === 'number'"
        :id="`dform-${field.name}`"
        type="number"
        :name="field.name"
        :required="field.required"
        v-model.number="values[field.name]"
      />
      <textarea
        v-else-if="field.type === 'textarea'"
        :id="`dform-${field.name}`"
        :name="field.name"
        :required="field.required"
        rows="4"
        v-model="values[field.name] as any"
      />
      <select
        v-else-if="field.type === 'select'"
        :id="`dform-${field.name}`"
        :name="field.name"
        :required="field.required"
        v-model="values[field.name] as any"
      >
        <option v-for="opt in (field.options ?? [])" :key="opt" :value="opt">{{ opt }}</option>
      </select>
      <label v-else-if="field.type === 'checkbox'" class="forge-canvas-form__checkbox">
        <input
          :id="`dform-${field.name}`"
          type="checkbox"
          :name="field.name"
          v-model="values[field.name] as any"
        />
        <span>{{ field.description || field.label }}</span>
      </label>

      <p
        v-if="field.description && field.type !== 'checkbox'"
        class="forge-canvas-form__help"
      >
        {{ field.description }}
      </p>
    </div>
    <footer class="forge-canvas-form__footer">
      <button type="button" class="forge-canvas-form__cancel" @click="emit('cancel')">
        {{ props.cancelLabel || 'Cancel' }}
      </button>
      <button type="submit" class="forge-canvas-form__submit">
        {{ props.submitLabel || 'Submit' }}
      </button>
    </footer>
  </form>
</template>

<style scoped>
.forge-canvas-form { display: flex; flex-direction: column; gap: 1rem; padding: 1rem 1.25rem; background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; }
.forge-canvas-form__header h3 { margin: 0 0 0.5rem 0; font-size: 1.1rem; }
.forge-canvas-form__field { display: flex; flex-direction: column; gap: 0.25rem; }
.forge-canvas-form__field label { font-weight: 500; font-size: 0.875rem; }
.forge-canvas-form__required { color: var(--fc-destructive, #dc2626); margin-left: 0.125rem; }
.forge-canvas-form__field input, .forge-canvas-form__field textarea, .forge-canvas-form__field select { padding: 0.5rem 0.625rem; border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.375rem; font-size: 0.875rem; font-family: inherit; }
.forge-canvas-form__field input:focus, .forge-canvas-form__field textarea:focus, .forge-canvas-form__field select:focus { outline: 2px solid var(--fc-primary, #2563eb); outline-offset: -1px; }
.forge-canvas-form__checkbox { flex-direction: row; align-items: center; gap: 0.5rem; }
.forge-canvas-form__checkbox input { width: auto; }
.forge-canvas-form__help { font-size: 0.75rem; color: var(--fc-muted-fg, #6b7280); margin: 0; }
.forge-canvas-form__footer { display: flex; gap: 0.5rem; justify-content: flex-end; padding-top: 0.25rem; }
.forge-canvas-form__submit { background: var(--fc-primary, #2563eb); color: white; padding: 0.5rem 1rem; border: none; border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
.forge-canvas-form__cancel { background: transparent; padding: 0.5rem 1rem; border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.375rem; cursor: pointer; font-size: 0.875rem; }
</style>
