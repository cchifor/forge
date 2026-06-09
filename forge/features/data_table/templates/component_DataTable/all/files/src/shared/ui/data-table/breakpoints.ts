import type { TailwindBreakpoint } from '@/shared/composables/useBreakpoint'

const BP_ORDER: TailwindBreakpoint[] = ['xs', 'sm', 'md', 'lg', 'xl', '2xl']

/**
 * True when ``current`` is a strictly smaller breakpoint than
 * ``threshold`` in Tailwind's xs → 2xl ordering. Used for
 * viewport-based fallback when no container width has been measured
 * (the container-driven path uses ``BP_WIDTH`` directly).
 */
export function twBelow(
  current: TailwindBreakpoint,
  threshold: TailwindBreakpoint,
): boolean {
  return BP_ORDER.indexOf(current) < BP_ORDER.indexOf(threshold)
}

/**
 * Pixel widths matching Tailwind's default breakpoints. Used for
 * container-driven ``responsiveHidden`` resolution: a column with
 * ``meta.responsiveHidden.below: 'lg'`` hides whenever the table's
 * container is narrower than 1024 px — the **container**, not the
 * viewport, so a chat-panel-narrowed table re-flows correctly.
 */
export const BP_WIDTH: Record<TailwindBreakpoint, number> = {
  xs: 0,
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
}
