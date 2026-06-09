const RTF =
  typeof Intl !== 'undefined' ? new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }) : null

export function formatAbsolute(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

export function formatRelative(iso: string | null, now: number = Date.now()): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return iso
  const diffMs = t - now
  const abs = Math.abs(diffMs)
  const sec = abs / 1000
  const min = sec / 60
  const hr = min / 60
  const day = hr / 24

  if (!RTF) {
    if (sec < 45) return 'just now'
    if (min < 60) return `${Math.round(min)}m`
    if (hr < 24) return `${Math.round(hr)}h`
    return `${Math.round(day)}d`
  }

  const sign = diffMs < 0 ? -1 : 1
  if (sec < 45) return RTF.format(0, 'second')
  if (min < 60) return RTF.format(sign * Math.round(min), 'minute')
  if (hr < 24) return RTF.format(sign * Math.round(hr), 'hour')
  return RTF.format(sign * Math.round(day), 'day')
}
