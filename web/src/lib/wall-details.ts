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
  scale_method?: string | null
  axis_source?: string | null
  notes: string[]
}

export function wallAskHref(docId: string, reference: string) {
  return `#/chat?doc=${encodeURIComponent(docId)}&question=${encodeURIComponent(`Tell me about wall ${reference}: its dimensions and face areas.`)}`
}

export function wallMeasure(value: number | null, unit: string) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} ${unit}` : 'Not available'
}

const f2 = (v: number) => v.toFixed(2)

/** Plain-language steps showing how each wall number was obtained, with the wall's own figures. */
export function howMeasured(wall: WallDetails): string[] {
  const lines: string[] = []
  const faces = wall.faces.filter((f) => f.gross_m2 !== null && f.net_m2 !== null)
  const formulas = faces.map((f) => `${f.label}: Net = ${f2(f.gross_m2!)} − ${f2(f.opening_m2 ?? f.gross_m2! - f.net_m2!)} = ${f2(f.net_m2!)} m²`)
  if (!faces.length) return lines
  if (wall.status === 'Measured') {
    lines.push('3D solid of the wall read from the IFC model twice: without openings (gross) and with door/window voids cut (net).',
      'Only the two long faces count; ends, top, bottom and opening reveals are excluded.',
      'Openings = area actually removed from each face by the cut, measured once even where voids overlap; not nominal door/window sizes.',
      "Inner/outer: the face touched by a room's space boundary is the inner face; IsExternal marks facade walls.")
  } else if (wall.status === 'Estimate') {
    lines.push(`Scale: ${wall.scale_method || /scale: (.+?)\.?$/.exec(wall.method)?.[1] || 'not available'}.`,
      `Length = half the outline perimeter${wall.length_m !== null ? ` (${f2(wall.length_m)} m)` : ''}.`,
      'Thickness = 2 × area / perimeter.',
      `Gross = perimeter × ${wall.height_m !== null ? `${f2(wall.height_m)} m` : 'height'} (${wall.height_source}).`,
      'Openings are already excluded as gaps in the outline, so nothing further is deducted.')
  } else return lines
  return [...lines, ...formulas]
}
