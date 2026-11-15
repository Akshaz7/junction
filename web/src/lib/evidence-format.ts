import type { EvidenceMargin, Reasoning } from './types'

// Keep uncertainty visible when it is smaller than a display decimal.
export function evidenceNumber(value: number): string {
  if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(2)
  return value.toLocaleString('en-GB', { maximumFractionDigits: 3 })
}

export function marginText(margin: EvidenceMargin): string {
  if (margin.value === null || !Number.isFinite(margin.value)) return `Margin not known — ${margin.why}`
  const unit = ({ m2: 'm²', m3: 'm³', count: 'elements' } as Record<string, string>)[margin.unit] ?? margin.unit
  const pct = margin.pct != null && Number.isFinite(margin.pct) ? ` (± ${evidenceNumber(margin.pct)}%)` : ''
  return `Margin: ± ${evidenceNumber(margin.value)} ${unit}${pct} — ${margin.why}`
}

export function confidenceText(confidence: Reasoning['confidence']): string {
  return confidence.pct != null && Number.isFinite(confidence.pct) ? `${confidence.label} · ${confidence.pct}%` : confidence.label
}
