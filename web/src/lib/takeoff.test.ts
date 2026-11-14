import { describe, expect, it } from 'vitest'
import { demoDocument, makeDemoAnswer } from '../mock/handler'
import { parseTakeoff, takeoffCsv } from './takeoff'

const md = ['Take-off for this file.', '', '| Item | Quantity | Unit | Source |', '| --- | --- | --- | --- |',
  '| Floor area - Kitchen, "main" | 12.5 | m2 | [1] |', '| Doors | 3 | count | [1] |', '| Piping - Water | not in this file |  |  |', '| =Evil | 1 | m | [9] |'].join('\n')
const make = () => { const a = makeDemoAnswer('How many windows are there?'); a.answer.text_md = md; return a }

describe('take-off sheet', () => {
  it('reads the table, resolves sources and flags missing rows', () => {
    const rows = parseTakeoff(make(), [demoDocument])!
    expect(rows).toHaveLength(4)
    expect(rows[0]).toMatchObject({ item: 'Floor area - Kitchen, "main"', quantity: '12.5', unit: 'm2', missing: false })
    expect(rows[0].source).toContain(demoDocument.title)
    expect(rows[2].missing).toBe(true)
    expect(rows[3].source).toBe('[9]')
  })
  it('returns null for answers without a take-off table', () => {
    const a = makeDemoAnswer('q'); a.answer.text_md = '| A | B |\n| - | - |\n| 1 | 2 |'
    expect(parseTakeoff(a)).toBeNull()
    a.answer.text_md = 'No table'
    expect(parseTakeoff(a)).toBeNull()
  })
  it('writes escaped CSV with a BOM and not-in-file rows blank', () => {
    const csv = takeoffCsv(parseTakeoff(make(), [demoDocument])!)
    const lines = csv.split('\r\n')
    expect(csv.startsWith('﻿Item,Quantity,Unit,Source')).toBe(true)
    expect(lines[1]).toContain('"Floor area - Kitchen, ""main"""')
    expect(lines[3]).toBe('Piping - Water,not in this file,,')
    expect(lines[4].startsWith("'=Evil")).toBe(true)
  })
})
