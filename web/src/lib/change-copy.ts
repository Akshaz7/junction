import type { Comparison } from './types'

type Item = Comparison['changes'][number]
export interface ChangeReading { change: Item; text: string; kind: 'note-added' | 'note-removed' | 'note-edited' | 'reference' | 'graphic-added' | 'graphic-removed' | 'graphic-edited' | 'rewritten'; small: boolean }

const short = (value: string, max = 40) => { const text = value.replace(/\s+/g, ' ').trim(); return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text }
const ref = /^[A-Z]{1,2}\s?-?\d{2,3}(\s?\/?\s?\d{1,2})?$/
const asRef = (value: string) => value.trim().replace(/^([A-Z]{1,2})\s?-?(\d{2,3})\s+(\d{1,2})$/, '$1$2/$3')

/** Where on the sheet a box sits, in words. */
export function whereOnSheet(box: [number, number, number, number] | null | undefined, size: { w: number; h: number }) {
  if (!box || !size.w || !size.h) return ''
  const x = (box[0] + box[2]) / 2 / size.w, y = (box[1] + box[3]) / 2 / size.h
  if (x > 0.84) return 'in the title block'
  const row = y < 1 / 3 ? 'top' : y > 2 / 3 ? 'bottom' : 'middle'
  const col = x < 1 / 3 ? 'left' : x > 2 / 3 ? 'right' : 'centre'
  return row === 'middle' && col === 'centre' ? 'near the middle of the sheet' : `near the ${row === 'middle' ? '' : `${row} `}${col} of the sheet`.replace('  ', ' ')
}

const area = (box: number[] | null | undefined, size: { w: number; h: number }) => box ? (box[2] - box[0]) * (box[3] - box[1]) / (size.w * size.h) : 0

/** Turn one engine sentence into plain words that say what changed and where. */
export function readChange(change: Item, size: { w: number; h: number }): ChangeReading {
  const s = change.sentence
  const bbox = (change.v2?.bbox_px || change.v1?.bbox_px) as [number, number, number, number] | null | undefined
  const where = whereOnSheet(bbox, size)
  const at = where ? ` ${where}` : ''
  let m = s.match(/^Text added: "([\s\S]*)"\.?$/)
  if (m) return { change, kind: 'note-added', small: false, text: `Note added${at}: "${short(m[1])}"` }
  m = s.match(/^Text removed: "([\s\S]*)"\.?$/)
  if (m) return { change, kind: 'note-removed', small: false, text: `Note removed${at}: "${short(m[1])}"` }
  m = s.match(/^Text changed from "([\s\S]*?)(?:…)?" to "([\s\S]*?)(?:…)?"\.?$/)
  if (m) {
    const [from, to] = [m[1].trim(), m[2].trim()]
    if (ref.test(from) && ref.test(to)) return { change, kind: 'reference', small: false, text: `Sheet reference changed: ${asRef(from)} → ${asRef(to)}` }
    if (from.length <= 24 && to.length <= 24 && !s.includes('…')) return { change, kind: 'note-edited', small: false, text: `Note edited${at}: "${from}" → "${to}"` }
    return { change, kind: 'rewritten', small: false, text: `Text rewritten${at}` }
  }
  const tiny = area(bbox, size) < 0.015
  if (/^Content added/.test(s)) return { change, kind: 'graphic-added', small: tiny, text: tiny ? 'Small linework added' : `New drawing content added${at}` }
  if (/^Content removed/.test(s)) return { change, kind: 'graphic-removed', small: tiny, text: tiny ? 'Small linework removed' : `Drawing content removed${at}` }
  if (/^Changed region/.test(s)) return { change, kind: 'graphic-edited', small: tiny, text: tiny ? 'Small linework edited' : `Drawing changed${at}` }
  return { change, kind: 'graphic-edited', small: false, text: s }
}

/** "25 changes: 3 notes edited, 2 added, 4 removed, 12 small linework edits." */
export function summariseChanges(readings: ChangeReading[]) {
  if (!readings.length) return 'No differences found.'
  const count = (kinds: ChangeReading['kind'][]) => readings.filter((r) => kinds.includes(r.kind)).length
  const n = (k: number, one: string, many: string) => k ? [`${k} ${k === 1 ? one : many}`] : []
  const text = [
    ...n(count(['note-edited', 'rewritten']), 'note edited', 'notes edited'), ...n(count(['reference']), 'sheet reference changed', 'sheet references changed'),
    ...n(count(['note-added']), 'note added', 'notes added'), ...n(count(['note-removed']), 'note removed', 'notes removed'),
    ...n(readings.filter((r) => !r.small && r.kind.startsWith('graphic')).length, 'drawing area changed', 'drawing areas changed'),
    ...n(readings.filter((r) => r.small).length, 'small linework edit', 'small linework edits'),
  ].join(', ')
  return `${readings.length} ${readings.length === 1 ? 'change' : 'changes'}: ${text}.`
}
