import { parseBlocks, plainQuote } from './answer-text'
import type { Answer, Document } from './types'

export const TAKEOFF_QUESTION = 'Give me a quantity take-off'
export const NOT_IN_FILE = 'not in this file'

export interface TakeoffRow { item: string; quantity: string; unit: string; source: string; missing: boolean }

const clean = (text: string) => plainQuote(text).replace(/\s+/g, ' ').trim()

/** The take-off table of an answer: the first pipe table headed Item | Quantity, else null. */
export function parseTakeoff(answer: Answer, docs: Document[] = []): TakeoffRow[] | null {
  const block = parseBlocks(answer.answer.text_md).find((item) => item.type === 'table' && /^item$/i.test(clean(item.header[0] ?? '')) && /^quantity$/i.test(clean(item.header[1] ?? '')))
  if (!block || block.type !== 'table') return null
  const unitAt = block.header.findIndex((cell) => /^unit$/i.test(clean(cell)))
  const sourceAt = block.header.findIndex((cell) => /^source/i.test(clean(cell)))
  return block.rows.map((cells) => {
    const quantity = clean(cells[1] ?? '')
    const markers = [...(sourceAt >= 0 ? cells[sourceAt] ?? '' : '').matchAll(/\[(\d+)\]/g)].map((match) => Number(match[1]))
    const source = markers.map((n) => {
      const citation = answer.citations.find((item) => item.n === n)
      if (!citation) return `[${n}]`
      const title = docs.find((doc) => doc.doc_id === citation.doc_id)?.title ?? citation.doc_id
      return `${title} p.${citation.page}`
    }).join('; ')
    return { item: clean(cells[0] ?? ''), quantity, unit: unitAt >= 0 ? clean(cells[unitAt] ?? '') : '', source, missing: !quantity || quantity.toLowerCase().startsWith(NOT_IN_FILE) }
  })
}

const field = (value: string) => {
  // Spreadsheet formula injection: a leading = + - @ in text is neutralised, numbers pass through.
  const safe = /^[=+@]/.test(value) || (/^-/.test(value) && !/^-?\d/.test(value)) ? `'${value}` : value
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

export function takeoffCsv(rows: TakeoffRow[]): string {
  const lines = [['Item', 'Quantity', 'Unit', 'Source'], ...rows.map((row) => [row.item, row.missing ? NOT_IN_FILE : row.quantity, row.missing ? '' : row.unit, row.missing ? '' : row.source])]
  return `﻿${lines.map((line) => line.map(field).join(',')).join('\r\n')}\r\n`
}

export function downloadTakeoffCsv(rows: TakeoffRow[], name = 'take-off.csv') {
  const url = URL.createObjectURL(new Blob([takeoffCsv(rows)], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = name
  document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
