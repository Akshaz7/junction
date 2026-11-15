/** Deterministic measurements for the 2D item panel: friendly rows, plain provenance, and the leftover source props. */

export interface MeasuredRow { label: string; value: string; key: string }

type Values = Record<string, unknown>

const UNIT: Record<string, string> = { m: 'm', m2: 'm²', m3: 'm³' }
const UNIT_KEY = /_(m|m2|m3)$/
/** Geometry internals and the raw provenance object: never listed as source properties. */
export const HIDDEN_PROP_KEYS: readonly string[] = ['measure', 'hinge', 'swing_bbox']
const INTERNAL_KEY = /_(pt|px)$/
const LENGTHS: [string, string][] = [['width_m', 'Width'], ['height_m', 'Height'], ['thickness_m', 'Thickness'], ['length_m', 'Length'], ['depth_m', 'Depth']]

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const fmt = (v: number) => Number.isInteger(v) ? String(v) : v.toFixed(2)
const withUnit = (v: number, unit: string) => `${v.toFixed(2)} ${UNIT[unit]}`
const present = (v: unknown) => v !== null && v !== undefined && v !== '' && !(typeof v === 'number' && !Number.isFinite(v))

/** Length and thickness are already in the wall details block; a wall with wall_details must not list them twice. */
export function withoutWallDetailRows(rows: MeasuredRow[]): MeasuredRow[] {
  return rows.filter((row) => !/^(length|thickness)(_|$)/.test(row.key.replace(/^quantity\./, '')))
}

function humanise(key: string) {
  const words = key.replace(UNIT_KEY, '').replace(/_/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : key
}

function roomType(value: string) {
  if (value.toLowerCase() === 'wc') return 'WC'
  return humanise(value)
}

function swing(value: unknown) {
  if (value === 'cw') return 'Clockwise'
  if (value === 'ccw') return 'Anticlockwise'
  return typeof value === 'string' && value ? value : null
}

/** Rows plus the prop keys they used (so sourceProps does not repeat them). */
function build(props: Values, quantities: Values = {}) {
  const rows: MeasuredRow[] = []
  const usedProps = new Set<string>()
  const usedQuantities = new Set<string>()
  const pick = (key: string): unknown => {
    if (present(props[key])) { usedProps.add(key); return props[key] }
    if (present(quantities[key])) { usedQuantities.add(key); return quantities[key] }
    return undefined
  }
  const number = pick('number')
  if (present(number) && (typeof number === 'string' || finite(number))) rows.push({ label: 'Room number', value: String(number), key: 'number' })
  const type = pick('room_type')
  if (typeof type === 'string' && type) rows.push({ label: 'Room type', value: roomType(type), key: 'room_type' })
  for (const [key, label] of LENGTHS) {
    const v = pick(key)
    if (finite(v)) rows.push({ label, value: withUnit(v, 'm'), key })
  }
  const printed = pick('area_m2_label'), measured = pick('area_m2_geom')
  if (finite(printed)) rows.push({ label: 'Area (printed)', value: withUnit(printed, 'm2'), key: 'area_m2_label' })
  if (finite(measured)) rows.push({ label: 'Area (measured from outline)', value: withUnit(measured, 'm2'), key: 'area_m2_geom' })
  if (finite(printed) || finite(measured)) {
    // area_m2 repeats one of the two above; the other area_m2* quantities repeat them too.
    if ('area_m2' in props) usedProps.add('area_m2')
    for (const key of Object.keys(quantities)) if (key.startsWith('area_m2')) usedQuantities.add(key)
  } else {
    const area = pick('area_m2')
    if (finite(area)) rows.push({ label: 'Area', value: withUnit(area, 'm2'), key: 'area_m2' })
  }
  const turn = swing(pick('swing'))
  if (turn) rows.push({ label: 'Swing', value: turn, key: 'swing' })
  const double = pick('double')
  if (typeof double === 'boolean') rows.push({ label: 'Double leaf', value: double ? 'Yes' : 'No', key: 'double' })
  const shown = new Set(rows.map((row) => row.key))
  for (const [key, v] of Object.entries(props)) {
    const unit = UNIT_KEY.exec(key)?.[1]
    if (!unit || shown.has(key) || usedProps.has(key) || !finite(v)) continue
    usedProps.add(key); shown.add(key)
    rows.push({ label: humanise(key), value: withUnit(v, unit), key })
  }
  for (const [key, v] of Object.entries(quantities)) {
    if (shown.has(key) || usedQuantities.has(key) || !finite(v)) continue
    const unit = UNIT_KEY.exec(key)?.[1]
    rows.push({ label: humanise(key), value: unit ? withUnit(v, unit) : fmt(v), key: `quantity.${key}` })
  }
  return { rows, usedProps }
}

/** `kind` is accepted for callers; the rows are driven by which keys are present, so any kind works. */
export function measuredRows(_kind: string | null, props: Values, quantities?: Values): MeasuredRow[] {
  return build(props ?? {}, quantities && typeof quantities === 'object' ? quantities : {}).rows
}

/** The props left for the raw "Source properties" list. */
export function sourceProps(props: Values): Values {
  const { usedProps } = build(props ?? {})
  return Object.fromEntries(Object.entries(props ?? {}).filter(([key]) =>
    !HIDDEN_PROP_KEYS.includes(key) && !INTERNAL_KEY.test(key) && !usedProps.has(key)))
}

const pct = (v: number) => `${(Math.abs(v) * 100).toFixed(1)}%`

function scalePhrase(source: unknown) {
  if (typeof source !== 'string' || !source.trim()) return ''
  const s = source.trim()
  const printed = /^printed\s+(1:\S+)$/i.exec(s)
  if (printed) return ` at the printed scale ${printed[1]}`
  switch (s.toLowerCase()) {
    case 'scale bar': return ' using the printed scale bar'
    case 'printed areas fit': return ' with the scale fitted to the printed room areas'
    case 'dimensions': return ' with the scale taken from printed dimensions'
    case 'door guess': return ' with the scale estimated from typical door widths'
    case 'unknown': return ', scale source unknown'
    default: return ` using the scale from ${s}`
  }
}

/** One plain sentence about where the numbers came from, built only from props.measure. */
export function measureProvenance(props: Values): string | null {
  const m = props?.measure
  if (!m || typeof m !== 'object' || Array.isArray(m)) return null
  const measure = m as Values
  const from = typeof measure.from === 'string' && measure.from.trim() ? measure.from.trim() : null
  let text = from === 'pdf_vector' ? "Read from the PDF's vector lines" : from ? `Measured from ${from.replace(/_/g, ' ')}` : 'Measured'
  text += scalePhrase(measure.scale_source)
  const check = measure.scale_check && typeof measure.scale_check === 'object' ? measure.scale_check as Values : {}
  const n = check.fit_n, err = check.printed_areas_rel_err
  if (finite(n) || finite(err)) {
    text += `, checked against ${finite(n) ? `${n} ` : ''}printed room area${n === 1 ? '' : 's'}`
    if (finite(err)) text += ` (${pct(err)} off)`
  }
  if (check.agree_2pct === false && finite(check.fit_vs_printed_rel))
    text += `; the fitted scale is ${pct(check.fit_vs_printed_rel)} off the printed scale, outside the 2% check`
  text += '.'
  if (finite(measure.printed_rel_err)) text += ` This outline's area is ${pct(measure.printed_rel_err)} off its printed area.`
  return text === 'Measured.' ? null : text
}

export function itemAskHref(docId: string, kind: string | null, reference: string) {
  const question = `Tell me about ${kind || 'item'} ${reference}: its size and where it is.`
  return `#/chat?doc=${encodeURIComponent(docId)}&question=${encodeURIComponent(question)}`
}
