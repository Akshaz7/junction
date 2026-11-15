import type { Answer, Bbox, Calculation, CalculationSource, Citation, ClaimsCalculation } from './types'

type Row = Calculation['rows'][number]

/** Numbers in the technical view: enough digits to show small scales (0.02903), no padding zeros. */
export function fmt(value: unknown, digits?: number): string {
  if (typeof value === 'string') return value
  if (typeof value !== 'number' || !Number.isFinite(value)) return value == null ? '-' : String(value)
  if (value !== 0 && Math.abs(value) < 0.0001) return value.toExponential(2)
  const max = digits ?? (Math.abs(value) >= 1000 ? 1 : Math.abs(value) >= 100 ? 2 : Math.abs(value) >= 1 ? 3 : 5)
  return value.toLocaleString('en-GB', { maximumFractionDigits: max })
}

const UNIT_WORDS: Record<string, string> = { m2: 'm²', m3: 'm³', count: '', px: 'px', 'm/px': 'm/px' }
export const unitText = (unit: string | undefined | null) => (unit ? (unit in UNIT_WORDS ? UNIT_WORDS[unit] : unit.replace('2', '²').replace('3', '³')) : '')
export const withUnit = (value: unknown, unit?: string | null) => `${fmt(value)}${unitText(unit) ? ` ${unitText(unit)}` : ''}`

const COLUMN_WORDS: Record<string, string> = { area_m2: 'Area (m²)', volume_m3: 'Volume (m³)', length_m: 'Length (m)', count: 'Count', width_m: 'Width (m)', height_m: 'Height (m)', perimeter_m: 'Perimeter (m)' }
export function columnLabel(key: string): string {
  if (COLUMN_WORDS[key]) return COLUMN_WORDS[key]
  const m = key.match(/^(.*)_(m2|m3|m|px|mm)$/)
  const base = (m ? m[1] : key).replace(/_/g, ' ')
  const cap = base.charAt(0).toUpperCase() + base.slice(1)
  return m ? `${cap} (${unitText(m[2]) || m[2]})` : cap
}

export function columnKeys(rows: Row[]): string[] {
  const keys: string[] = []
  for (const row of rows) for (const key of Object.keys(row.values ?? {})) if (!keys.includes(key)) keys.push(key)
  return keys
}

export type RowSort = { key: string; dir: 'asc' | 'desc' } | null
const cell = (row: Row, key: string): unknown => key === '__label' ? row.label : row.values?.[key]

/** Stable sort: numbers by value, text alphabetically, missing values last. */
export function sortRows(rows: Row[], sort: RowSort): Row[] {
  if (!sort) return rows
  const sign = sort.dir === 'asc' ? 1 : -1
  return rows.map((row, index) => ({ row, index })).sort((a, b) => {
    const x = cell(a.row, sort.key), y = cell(b.row, sort.key)
    if (x == null && y == null) return a.index - b.index
    if (x == null) return 1
    if (y == null) return -1
    const d = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'en', { numeric: true })
    return d * sign || a.index - b.index
  }).map((entry) => entry.row)
}

export function pageRows<T>(rows: T[], page: number, size: number): { rows: T[]; pages: number; page: number } {
  const pages = Math.max(1, Math.ceil(rows.length / size))
  const at = Math.min(Math.max(0, page), pages - 1)
  return { rows: rows.slice(at * size, at * size + size), pages, page: at }
}

const RESULT_KEY: Record<string, string> = { count: 'count', rooms: 'count', m: 'length_m', m2: 'area_m2', m3: 'volume_m3' }

export type Totals = { sums: Record<string, number>; count: number; reconciles: boolean | null; note: string }
/** Column sums over ALL rows (not only the visible page), and whether they equal the result. */
export function totalsOf(calc: Pick<Calculation, 'rows' | 'result'>): Totals {
  const sums: Record<string, number> = {}
  for (const key of columnKeys(calc.rows)) {
    let total = 0, any = false
    for (const row of calc.rows) { const v = row.values?.[key]; if (typeof v === 'number' && Number.isFinite(v)) { total += v; any = true } }
    if (any) sums[key] = total
  }
  const result = calc.result?.value
  if (typeof result !== 'number') return { sums, count: calc.rows.length, reconciles: null, note: '' }
  const unit = calc.result.unit
  const key = RESULT_KEY[unit] ?? ''
  const total = key in sums ? sums[key] : unit === 'count' || unit === 'rooms' ? calc.rows.length : undefined
  if (total === undefined) return { sums, count: calc.rows.length, reconciles: null, note: '' }
  const tol = Math.max(1e-6 * Math.abs(result), calc.result.rounded_as?.includes('1 decimal') ? 0.05 : calc.result.rounded_as?.includes('2 decimal') ? 0.005 : 0.5e-3)
  const ok = Math.abs(total - result) <= tol
  return { sums, count: calc.rows.length, reconciles: ok, note: ok ? 'Rows add up to the result.' : `Rows add up to ${fmt(total)}, the result is ${fmt(result)}: see the steps for what was left out or added.` }
}

export type FocusTarget = { item_id: string; doc_id?: string; page?: number; bbox?: Bbox; cite?: number | null }
/** What a source points at on the drawing, if anything the viewer can highlight. */
export function focusOf(source: CalculationSource | undefined): FocusTarget | null {
  if (!source?.item_id && !source?.bbox) return null
  return { item_id: source.item_id || `source-${source.page ?? 1}-${source.bbox!.join('-')}`, ...(source.doc_id ? { doc_id: source.doc_id } : {}), ...(source.page != null ? { page: source.page } : {}), ...(source.bbox ? { bbox: source.bbox } : {}) }
}

/** A calculation can open its source document even if the answer has no citation chips. */
export function calculationCitation(answer: Answer): Citation | undefined {
  if (answer.citations[0]) return answer.citations[0]
  const source = answer.reasoning?.calc?.steps?.flatMap((step) => step.inputs ?? []).find((input) => input.source?.doc_id)?.source
  const docId = source?.doc_id || answer.doc_ids[0] || answer.evidence.scene.doc_id
  if (!docId) return undefined
  return { n: 1, doc_id: docId, page: source?.page ?? 1, kind: 'region', bbox_px: source?.bbox ?? null, item_ids: source?.item_id ? [source.item_id] : [], quote: null }
}

export function sourceText(source: CalculationSource | undefined, docTitle?: (id: string) => string): string {
  if (!source) return 'no source recorded'
  const parts: string[] = []
  const file = source.doc_id ? (docTitle?.(source.doc_id) ?? source.doc_id) : source.artifact
  if (file) parts.push(file)
  if (source.page != null) parts.push(`page ${source.page}`)
  if (source.item_id) parts.push(`item ${source.item_id}`)
  if (source.field) parts.push(source.field)
  if (source.step_id) parts.push(`step ${source.step_id}`)
  if (source.text) parts.push(`"${source.text}"`)
  return parts.length ? parts.join(' · ') : source.origin || source.kind || 'no source recorded'
}

/** Signed percentage points: +3, -12.5. */
export const signed = (delta: number) => `${delta > 0 ? '+' : delta < 0 ? '−' : ''}${fmt(Math.abs(delta), 1)}`

/** The headline numbers for the compact card: result, scale, a few counts, margin. */
/** The few numbers for the compact card. Driven only by what the calculation contains: no step names are assumed. */
export function keyNumbers(calc: Calculation | ClaimsCalculation | undefined): { label: string; text: string }[] {
  if (!calc) return []
  if (calc.kind === 'claims') return [
    { label: 'Method', text: calc.method.label },
    { label: 'Claims', text: `${calc.result.claims_total} total · ${calc.result.verified} verified · ${calc.result.read_only} read only · ${calc.result.inferred} inferred` },
  ]
  const out: { label: string; text: string }[] = []
  const r = calc.result
  if (r && typeof r.value === 'number') out.push({ label: 'Result', text: withUnit(r.value, r.unit) })
  if (calc.method?.label) out.push({ label: 'Method', text: calc.method.label })
  const m = calc.margin
  if (m && m.value != null && Number.isFinite(m.value)) out.push({ label: 'Margin', text: `± ${withUnit(m.value, m.unit)}${m.pct != null ? ` (± ${fmt(m.pct, 2)}%)` : ''}` })
  const judged = (calc.checks ?? []).filter((c) => c.agrees != null)
  if (judged.length) out.push({ label: 'Checks', text: `${judged.filter((c) => c.agrees).length} of ${judged.length} agree` })
  return out
}
