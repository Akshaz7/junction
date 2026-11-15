/**
 * One fixed colour per item kind, shared by the 2D evidence boxes, the 3D highlights and the
 * legend. Okabe-Ito based (colour-blind safe). The same table is mirrored in
 * public/kind-colors.json so iOS can copy the values; kind-colors.test.ts keeps them equal.
 */
export const KIND_KEYS = ['door', 'window', 'wall', 'room', 'toilet', 'sink', 'shower', 'bathtub', 'stairs', 'pipe', 'drain', 'fitting', 'beam', 'member', 'column', 'slab', 'other'] as const
export type KindKey = typeof KIND_KEYS[number]

export interface KindStyle {
  /** Fill/stroke/glow colour. */
  color: string
  /** Text colour that stays readable on `color` (label chips). */
  on: string
  label: string
  plural: string
}

export const KIND_COLORS: Record<KindKey, KindStyle> = {
  door: { color: '#D55E00', on: '#FFFFFF', label: 'Door', plural: 'Doors' },
  window: { color: '#0072B2', on: '#FFFFFF', label: 'Window', plural: 'Windows' },
  wall: { color: '#E69F00', on: '#1A1A1A', label: 'Wall', plural: 'Walls' },
  room: { color: '#009E73', on: '#FFFFFF', label: 'Room', plural: 'Rooms' },
  toilet: { color: '#CC79A7', on: '#1A1A1A', label: 'Toilet', plural: 'Toilets' },
  sink: { color: '#56B4E9', on: '#1A1A1A', label: 'Sink', plural: 'Sinks' },
  shower: { color: '#F0E442', on: '#1A1A1A', label: 'Shower', plural: 'Showers' },
  bathtub: { color: '#882255', on: '#FFFFFF', label: 'Bathtub', plural: 'Bathtubs' },
  stairs: { color: '#999933', on: '#FFFFFF', label: 'Stairs', plural: 'Stairs' },
  pipe: { color: '#332288', on: '#FFFFFF', label: 'Pipe', plural: 'Pipes' },
  drain: { color: '#8C510A', on: '#FFFFFF', label: 'Drain', plural: 'Drains' },
  fitting: { color: '#B2182B', on: '#FFFFFF', label: 'Fitting', plural: 'Fittings' },
  beam: { color: '#117733', on: '#FFFFFF', label: 'Beam', plural: 'Beams' },
  member: { color: '#44AA99', on: '#1A1A1A', label: 'Member', plural: 'Members' },
  column: { color: '#AA4499', on: '#FFFFFF', label: 'Column', plural: 'Columns' },
  slab: { color: '#6699CC', on: '#1A1A1A', label: 'Slab', plural: 'Slabs' },
  other: { color: '#7F7F7F', on: '#FFFFFF', label: 'Other', plural: 'Other' },
}

const ALIASES: Record<string, KindKey> = {
  curtain_wall: 'wall', stair: 'stairs', stairflight: 'stairs', stair_flight: 'stairs', sanitary: 'toilet', wc: 'toilet',
  pipe_segment: 'pipe', pipe_fitting: 'fitting', valve: 'fitting', valve_damper: 'fitting', pipefitting: 'fitting', pipesegment: 'pipe',
}

/** Maps any manifest/plan-map kind (or null) onto one of the ten colour keys. */
export function kindKey(kind: string | null | undefined): KindKey {
  const k = (kind ?? '').toLowerCase()
  if ((KIND_KEYS as readonly string[]).includes(k)) return k as KindKey
  return ALIASES[k] ?? 'other'
}

const DRAIN = /abwasser|schmutz|drain|waste|sewer|sewage|regenwasser|storm|ht\b|afvoer|riool/i

/** Colour key for a manifest item: pipes carrying waste (system/type/name) are drains, everything else follows `kind`. */
export function itemKindKey(item: { kind: string; name?: string | null; props?: Record<string, unknown> | null } | null | undefined): KindKey {
  if (!item) return 'other'
  const key = kindKey(item.kind)
  if (key !== 'pipe') return key
  const p = item.props ?? {}
  const text = [item.name, p.system, p.type_name, p.system_name].filter((v) => typeof v === 'string').join(' ')
  return DRAIN.test(text) ? 'drain' : 'pipe'
}

/** Pipe size group ("DN100") when the manifest carries the nominal diameter, else null. */
export function pipeSizeLabel(item: { kind: string; props?: Record<string, unknown> | null } | null | undefined): string | null {
  const dn = item?.props?.dn_mm
  return item && kindKey(item.kind) === 'pipe' && typeof dn === 'number' && dn > 0 ? `DN${Math.round(dn)}` : null
}

export function kindStyle(kind: string | null | undefined): KindStyle { return KIND_COLORS[kindKey(kind)] }
export function kindColor(kind: string | null | undefined): string { return kindStyle(kind).color }

/** Plan-map item ids are `<kind>-<3 digits>` (CONTRACT 2); anything else (IFC GlobalIds) needs a manifest lookup. */
export function kindFromItemId(itemId: string): string | null {
  const match = /^([a-z_]+)-\d+$/.exec(itemId)
  return match ? match[1] : null
}

/** "Windows 11 · Doors 11": counts per colour key, in first-seen order. */
export function kindCounts(kinds: readonly (string | null | undefined)[]): { key: KindKey; count: number }[] {
  const counts = new Map<KindKey, number>()
  for (const kind of kinds) counts.set(kindKey(kind), (counts.get(kindKey(kind)) ?? 0) + 1)
  return [...counts].map(([key, count]) => ({ key, count }))
}

export function kindColorsJson(): string {
  return JSON.stringify({ version: 1, source: 'web/src/lib/kind-colors.ts', palette: 'Okabe-Ito', kinds: KIND_COLORS }, null, 2) + '\n'
}
