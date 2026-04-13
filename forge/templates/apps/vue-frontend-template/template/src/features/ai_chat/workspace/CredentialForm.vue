<script setup lang="ts">
import { reactive, computed } from 'vue'
import { Eye, EyeOff } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import type { WorkspaceActivity, AgentState, WorkspaceAction } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: WorkspaceAction]
}>()

interface FieldDef {
  name: string
  label: string
  type: string
  required?: boolean
}

const fields = computed<FieldDef[]>(() => {
  if (Array.isArray(props.activity.content.fields) && props.activity.content.fields.length > 0) {
    return props.activity.content.fields
  }
  return [{ name: 'password', label: 'Password', type: 'password', required: true }]
})

const formValues = reactive<Record<string, string>>({})
const showPassword = reactive<Record<string, boolean>>({})

function isPasswordField(field: FieldDef) {
  return field.type === 'password'
}

function toggleVisibility(fieldName: string) {
  showPassword[fieldName] = !showPassword[fieldName]
}

function handleSubmit() {
  emit('action', {
    type: 'submit_credentials',
    data: { ...formValues },
  })
}
</script>

<template>
  <form class="flex flex-col gap-4 p-4" @submit.prevent="handleSubmit">
    <p v-if="activity.content.description" class="text-sm text-muted-foreground">
      {{ activity.content.description }}
    </p>

    <div v-for="field in fields" :key="field.name" class="flex flex-col gap-1.5">
      <label :for="field.name" class="text-sm font-medium">
        {{ field.label }}
        <span v-if="field.required" class="text-destructive">*</span>
      </label>
      <div class="relative">
        <input
          :id="field.name"
          v-model="formValues[field.name]"
          :type="isPasswordField(field) && !showPassword[field.name] ? 'password' : 'text'"
          :required="field.required"
          class="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus:ring-2 focus:ring-ring focus:ring-offset-2"
          :placeholder="field.label"
        />
        <button
          v-if="isPasswordField(field)"
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          @click="toggleVisibility(field.name)"
        >
          <EyeOff v-if="showPassword[field.name]" class="h-4 w-4" />
          <Eye v-else class="h-4 w-4" />
        </button>
      </div>
    </div>

    <Button type="submit" class="mt-2 w-full">
      Submit
    </Button>
  </form>
</template>
