export interface WallDetails {
  status: 'Measured' | 'Estimate' | 'Not available'
  length_m: number | null
  thickness_m: number | null
  height_m: number | null
  height_source: string
  storey: string | null
  classification: string
  faces: { label: string; gross_m2: number | null; opening_m2: number | null; net_m2: number | null }[]
  opening_count: number | null
  method: string
  notes: string[]
}

export function wallAskHref(docId: string, reference: string) {
  return `#/chat?doc=${encodeURIComponent(docId)}&question=${encodeURIComponent(`Tell me about wall ${reference}: its dimensions and face areas.`)}`
}

export function wallMeasure(value: number | null, unit: string) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} ${unit}` : 'Not available'
}
