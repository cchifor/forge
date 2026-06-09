<script setup lang="ts">
import { SwitchRoot, SwitchThumb, type SwitchRootProps } from 'radix-vue'
import { type HTMLAttributes, computed } from 'vue'
import { cn } from '@/shared/lib/utils'

// Radix Vue's SwitchRoot is the underlying primitive; its native prop is
// ``checked`` / event ``update:checked``. We also accept ``modelValue`` /
// ``update:modelValue`` so call sites that prefer the Vue ``v-model``
// convention work — but ``checked`` is the canonical path.
type Props = SwitchRootProps & {
  class?: HTMLAttributes['class']
  modelValue?: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{
  'update:checked': [value: boolean]
  'update:modelValue': [value: boolean]
}>()

const effectiveChecked = computed<boolean | undefined>(() =>
  props.checked !== undefined ? props.checked : props.modelValue,
)

function onCheckedUpdate(value: boolean): void {
  emit('update:checked', value)
  emit('update:modelValue', value)
}
</script>

<template>
  <SwitchRoot
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
        'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
        props.class,
      )
    "
    @update:checked="onCheckedUpdate"
  >
    <SwitchThumb
      class="pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0"
    />
  </SwitchRoot>
</template>
