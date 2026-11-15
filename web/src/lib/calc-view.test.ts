import { expect, it } from 'vitest'
import { columnLabel, fmt, focusOf, keyNumbers, pageRows, signed, sortRows, sourceText, totalsOf, withUnit } from './calc-view'
import { scanCalc, areaCalc } from './__fixtures__/calc-fixture'

it('formats numbers for the technical view', () => {
  expect(fmt(0.02903)).toBe('0.02903')
  expect(fmt(0.00001234)).toBe('1.23e-5')
  expect(fmt(1234.56)).toBe('1,234.6')
  expect(withUnit(16.5, 'm2')).toBe('16.5 m²')
  expect(withUnit(40, 'count')).toBe('40')
  expect(signed(-12.5)).toBe('−12.5')
  expect(columnLabel('floor_area_m2')).toBe('Floor area (m²)')
})

it('sorts and pages rows, keeping missing values last', () => {
  const rows = areaCalc.rows
  const asc = sortRows(rows, { key: 'area_m2', dir: 'asc' })
  expect(asc[0].values.area_m2).toBeLessThanOrEqual(asc[1].values.area_m2 as number)
  const desc = sortRows(rows, { key: 'area_m2', dir: 'desc' })
  expect(desc[0].values.area_m2).toBeGreaterThanOrEqual(desc[1].values.area_m2 as number)
  expect(sortRows(rows, { key: '__label', dir: 'asc' })[0].label.localeCompare(rows[1].label, 'en', { numeric: true })).toBeLessThanOrEqual(0)
  const p = pageRows(rows, 99, 2)
  expect(p.page).toBe(p.pages - 1)
  expect(p.rows.length).toBeGreaterThan(0)
})

it('totals reconcile with the result over every row', () => {
  const t = totalsOf(areaCalc)
  expect(t.reconciles).toBe(true)
  const bad = totalsOf({ ...areaCalc, result: { ...areaCalc.result, value: 99 } })
  expect(bad.reconciles).toBe(false)
  expect(bad.note).toMatch(/result is 99/)
  expect(totalsOf(scanCalc).reconciles).toBe(true)  // count rows
})

it('says where a source is and what can be highlighted', () => {
  const src = { doc_id: 'd1', page: 1, item_id: 'door-3' }
  expect(sourceText(src, () => 'Plan A')).toBe('Plan A · page 1 · item door-3')
  expect(focusOf(src)).toEqual({ item_id: 'door-3', doc_id: 'd1', page: 1 })
  expect(focusOf({ doc_id: 'd1' })).toBeNull()
  expect(sourceText(undefined)).toBe('no source recorded')
})

it('picks the key numbers for the compact card', () => {
  const k = keyNumbers(scanCalc)
  expect(k.map((x) => x.label)).toEqual(expect.arrayContaining(['Result', 'Method', 'Margin', 'Checks']))
  expect(k.find((x) => x.label === 'Checks')?.text).toBe('1 of 2 agree')
  expect(keyNumbers(undefined)).toEqual([])
})
