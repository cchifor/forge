<script setup lang="ts">
import { type Component } from 'vue'
import { Button } from '@/shared/ui/button'

export interface FeatureEmptyStateAction {
  label: string
  icon?: Component
  onClick: () => void
}

defineProps<{
  icon: Component
  title: string
  body: string
  primaryAction?: FeatureEmptyStateAction
  secondaryAction?: FeatureEmptyStateAction
  illustration?: Component
}>()
</script>

<template>
  <div class="rounded-lg border border-dashed p-10 text-center">
    <div
      class="mx-auto flex max-w-md flex-col items-center gap-3 text-sm text-muted-foreground"
    >
      <component :is="illustration" v-if="illustration" />
      <component
        :is="icon"
        v-else
        class="h-12 w-12 text-muted-foreground/60"
        aria-hidden="true"
      />
      <p class="text-base font-medium text-foreground">{{ title }}</p>
      <p>{{ body }}</p>
      <div
        v-if="primaryAction || secondaryAction"
        class="flex flex-wrap justify-center gap-2 pt-2"
      >
        <Button v-if="primaryAction" @click="primaryAction.onClick()">
          <component
            :is="primaryAction.icon"
            v-if="primaryAction.icon"
            class="mr-1.5 h-4 w-4"
            aria-hidden="true"
          />
          {{ primaryAction.label }}
        </Button>
        <Button
          v-if="secondaryAction"
          variant="ghost"
          @click="secondaryAction.onClick()"
        >
          <component
            :is="secondaryAction.icon"
            v-if="secondaryAction.icon"
            class="mr-1.5 h-4 w-4"
            aria-hidden="true"
          />
          {{ secondaryAction.label }}
        </Button>
      </div>
    </div>
  </div>
</template>
