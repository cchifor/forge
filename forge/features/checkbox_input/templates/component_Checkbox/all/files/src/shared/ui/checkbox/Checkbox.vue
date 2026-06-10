<script setup lang="ts">
import { CheckboxRoot, CheckboxIndicator, type CheckboxRootProps } from 'radix-vue'
import { type HTMLAttributes, computed } from 'vue'
import { Check } from 'lucide-vue-next'
import { cn } from '@/shared/lib/utils'

// Radix Vue's CheckboxRoot is the underlying primitive; its native prop is
// ``checked`` / event ``update:checked``. We also accept ``modelValue`` /
// ``update:modelValue`` so call sites that prefer the Vue ``v-model``
// convention work — but ``checked`` is the canonical path.
type Props = CheckboxRootProps & {
  class?: HTMLAttributes['class']
  modelValue?: boolean | 'indeterminate'
}
const props = defineProps<Props>()
const emit = defineEmits<{
  'update:checked': [value: boolean]
  'update:modelValue': [value: boolean]
}>()

const effectiveChecked = computed<boolean | 'indeterminate' | undefined>(() =>
  props.checked !== undefined ? props.checked : props.modelValue,
)

function onCheckedUpdate(value: boolean): void {
  emit('update:checked', value)
  emit('update:modelValue', value)
}
</script>

<template>
  <CheckboxRoot
    :checked="effectiveChecked"
    :default-checked="defaultChecked"
    :disabled="disabled"
    :required="required"
    :name="name"
    :value="value"
    :id="id"
    :as-child="asChild"
    :as="as"
    :class="
      cn(
        'peer h-4 w-4 shrink-0 rounded-sm border border-primary shadow focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground',
        props.class,
      )
    "
    @update:checked="onCheckedUpdate"
  >
    <CheckboxIndicator class="flex items-center justify-center text-current">
      <Check class="h-3.5 w-3.5" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>
