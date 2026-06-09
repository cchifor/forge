import { computed, type ComputedRef } from 'vue'
import { useWindowSize } from '@vueuse/core'

/**
 * Tailwind-aligned breakpoint tiers, owned by the DataTable feature so it stays
 * self-contained: the base ``@/shared/composables/useBreakpoint`` only exposes
 * the coarse layout tiers (``compact``/``medium``/``expanded``), not the
 * Tailwind ladder the responsive-column logic needs.
 */
export type TailwindBreakpoint = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | '2xl'

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

/**
 * The current viewport Tailwind breakpoint tier, derived from the window
 * width. Viewport-based fallback for the responsive-column logic when no
 * container width has been measured yet (the container-driven path resolves
 * against ``BP_WIDTH`` directly). Self-contained so the feature doesn't depend
 * on a Tailwind tier in the base ``useBreakpoint``.
 */
export function useTwBreakpoint(): { tw: ComputedRef<TailwindBreakpoint> } {
  const { width } = useWindowSize()
  const tw = computed<TailwindBreakpoint>(() => {
    const w = width.value
    // Largest tier whose min-width the viewport meets (xs is the 0 floor).
    let current: TailwindBreakpoint = 'xs'
    for (const bp of BP_ORDER) {
      if (w >= BP_WIDTH[bp]) current = bp
    }
    return current
  })
  return { tw }
}
