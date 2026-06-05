<script setup lang="ts">
// BentoGrid — a Layer-2 presentational CSS-Grid wrapper for dashboard tiles.
//
// Generated dashboard pages compose this inside the standard <main> slot.
// Tiles are plain children; apply `col-span-2` / `row-span-2` on a child to
// create the asymmetric "bento" rhythm. Responsive column counts come from
// Tailwind breakpoints: 1 col (mobile) -> 2 cols (sm, 640px) -> 4 cols (lg, 1024px).
//
// These Tailwind breakpoints (640px / 1024px) are deliberately INDEPENDENT of
// the app-shell breakpoints in MainLayout (compact <600px, medium 600-839px,
// expanded >=840px). The shell breakpoints decide which chrome renders
// (sidebar vs. bottom nav vs. chat mode); BentoGrid only governs the inner
// tile mosaic. They are separate concerns and are not meant to align — e.g.
// at 600-639px the shell already shows the collapsed sidebar while the grid is
// still single-column, which is intentional.
//
// `auto-rows-[minmax(8rem,auto)]` sets a 128px (8rem) minimum row height so a
// plain single-cell tile is never shorter than one comfortable card; tiles with
// more content grow past it via the `auto` upper bound, and `row-span-2` tiles
// span two such tracks to form the tall bento cells.
//
// CSS Grid is intentional and allowed here: the bento mosaic is the one place
// the layout uses Grid; the surrounding app shell stays Flexbox.
</script>

<template>
  <div
    class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 auto-rows-[minmax(8rem,auto)]"
  >
    <slot />
  </div>
</template>
