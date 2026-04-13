<script setup lang="ts">
import { ref, computed } from 'vue'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Textarea } from '@/shared/ui/textarea'
import type { WorkspaceActivity, AgentState } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const schema = computed(() => props.activity.content.props || props.activity.content)
const fields = computed(() => schema.value.fields || [])
const values = ref<Record<string, any>>({})

// Initialize defaults
fields.value.forEach((f: any) => {
  if (f.default !== undefined) values.value[f.name] = f.default
  else if (f.type === 'toggle') values.value[f.name] = false
  else if (f.type === 'checkbox-group') values.value[f.name] = []
})

function toggleCheckbox(fieldName: string, option: string) {
  const arr = values.value[fieldName] || []
  const idx = arr.indexOf(option)
  if (idx >= 0) arr.splice(idx, 1)
  else arr.push(option)
  values.value[fieldName] = [...arr]
}

function submit() {
  emit('action', { type: 'form_submit', data: { values: { ...values.value } } })
}

function cancel() {
  emit('action', { type: 'form_cancel', data: {} })
}
</script>

<template>
  <div class="mx-auto max-w-2xl space-y-6 p-6">
    <div>
      <h2 class="text-lg font-semibold">{{ schema.title }}</h2>
      <p v-if="schema.description" class="text-sm text-muted-foreground">{{ schema.description }}</p>
    </div>

    <div class="space-y-4">
      <div v-for="field in fields" :key="field.name" class="space-y-1.5">
        <Label :for="field.name" class="text-sm font-medium">
          {{ field.label }}
          <span v-if="field.required" class="text-destructive">*</span>
        </Label>

        <!-- text / password / url / email / number -->
        <Input
          v-if="['text', 'password', 'url', 'email', 'number'].includes(field.type)"
          :id="field.name"
          v-model="values[field.name]"
          :type="field.type === 'number' ? 'number' : field.type"
          :placeholder="field.placeholder"
        />

        <!-- textarea -->
        <Textarea
          v-else-if="field.type === 'textarea'"
          :id="field.name"
          v-model="values[field.name]"
          :placeholder="field.placeholder"
          rows="3"
        />

        <!-- select -->
        <select
          v-else-if="field.type === 'select'"
          :id="field.name"
          v-model="values[field.name]"
          class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <option value="" disabled>{{ field.placeholder || 'Select...' }}</option>
          <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
        </select>

        <!-- toggle -->
        <div v-else-if="field.type === 'toggle'" class="flex items-center gap-2">
          <button
            type="button"
            role="switch"
            :aria-checked="!!values[field.name]"
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            :class="values[field.name] ? 'bg-primary' : 'bg-muted'"
            @click="values[field.name] = !values[field.name]"
          >
            <span
              class="pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform"
              :class="values[field.name] ? 'translate-x-4' : 'translate-x-0'"
            />
          </button>
          <span class="text-xs text-muted-foreground">{{ values[field.name] ? 'Enabled' : 'Disabled' }}</span>
        </div>

        <!-- checkbox-group -->
        <div v-else-if="field.type === 'checkbox-group'" class="flex flex-wrap gap-3">
          <label
            v-for="opt in field.options"
            :key="opt"
            class="flex items-center gap-1.5 text-sm cursor-pointer"
          >
            <input
              type="checkbox"
              :checked="(values[field.name] || []).includes(opt)"
              class="h-4 w-4 rounded border-input"
              @change="toggleCheckbox(field.name, opt)"
            />
            {{ opt }}
          </label>
        </div>
      </div>
    </div>

    <div class="flex gap-3 pt-2">
      <Button @click="submit">{{ schema.submitLabel || 'Submit' }}</Button>
      <Button v-if="schema.cancelLabel" variant="outline" @click="cancel">{{ schema.cancelLabel }}</Button>
    </div>
  </div>
</template>
