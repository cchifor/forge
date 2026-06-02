<script setup lang="ts">
// Layer-3 Console template page — composes the Layer-1 StatCard component.
import StatCard from '@/shared/components/StatCard.vue'
</script>

<template>
  <section class="console-dashboard grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
    <StatCard label="Total" :value="0" />
    <StatCard label="Active" :value="0" />
  </section>
</template>
