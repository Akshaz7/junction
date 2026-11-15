import { describe, expect, it } from 'vitest'
import { itemAskHref, measuredRows, measureProvenance, sourceProps } from './item-measures'

const measure = { from: 'pdf_vector', m_per_pt: 0.0352778, scale_source: 'printed 1:100',
  scale_check: { printed_areas_rel_err: 0.0236, fit_n: 17, fit_vs_printed_rel: 0.0169, agree_2pct: true }, geometry: 'polygon' }
const door = { width_m: 0.96, swing: 'cw', double: false, leaf: true, width_pt: 27.2, radius_pt: 27.2, depth_pt: 4,
  hinge: [10, 20], swing_bbox: [1, 2, 3, 4], measure }
const wall = { thickness_m: 0.268, length_m: 10.567, thickness_px: 11, style: 'fill', measure }
const room = { room_type: 'bedroom', number: '2.01', area_m2: 12.09, area_m2_label: 12.09, area_m2_geom: 11.48, labelled: true,
  measure: { ...measure, printed_rel_err: 0.0505 } }
const pairs = (rows: { label: string; value: string }[]) => rows.map((r) => [r.label, r.value])

describe('measuredRows', () => {
  it('labels a PDF door with units and words', () => {
    expect(pairs(measuredRows('door', door))).toEqual([['Width', '0.96 m'], ['Swing', 'Clockwise'], ['Double leaf', 'No']])
    expect(measuredRows('door', { ...door, swing: 'ccw', double: true }).map((r) => r.value)).toEqual(['0.96 m', 'Anticlockwise', 'Yes'])
  })
  it('rounds wall sizes to centimetres and never shows pt/px', () => {
    expect(pairs(measuredRows('wall', wall))).toEqual([['Thickness', '0.27 m'], ['Length', '10.57 m']])
  })
  it('shows printed and measured room areas separately', () => {
    expect(pairs(measuredRows('room', room))).toEqual([['Room number', '2.01'], ['Room type', 'Bedroom'],
      ['Area (printed)', '12.09 m²'], ['Area (measured from outline)', '11.48 m²']])
    expect(pairs(measuredRows('room', { area_m2: 7.5 }))).toEqual([['Area', '7.50 m²']])
  })
  it('adds quantities not already shown and skips missing values', () => {
    const rows = measuredRows('door', { width_m: 0.9, height_m: null, depth_m: Number.NaN },
      { width_m: 1, height_m: 2.1, perimeter_m: 6.2, area_m2: 2.1, volume_m3: 0.0993, count: 2, note: 'x' })
    expect(pairs(rows)).toEqual([['Width', '0.90 m'], ['Height', '2.10 m'], ['Area', '2.10 m²'],
      ['Perimeter', '6.20 m'], ['Volume', '0.10 m³'], ['Count', '2']])
    expect(measuredRows('room', room, { area_m2: 11.48, area_m2_printed: 12.09 })).toHaveLength(4)
    expect(measuredRows(null, {})).toEqual([])
  })
})

describe('measureProvenance', () => {
  it('states source, scale and the check from the measure object only', () => {
    expect(measureProvenance(door)).toBe("Read from the PDF's vector lines at the printed scale 1:100, checked against 17 printed room areas (2.4% off).")
    expect(measureProvenance(room)).toContain("This outline's area is 5.1% off its printed area.")
  })
  it('says plainly when the scale check failed and omits missing parts', () => {
    const failed = { measure: { ...measure, scale_check: { printed_areas_rel_err: 0.031, fit_n: 3, fit_vs_printed_rel: -0.035, agree_2pct: false } } }
    expect(measureProvenance(failed)).toBe("Read from the PDF's vector lines at the printed scale 1:100, checked against 3 printed room areas (3.1% off); the fitted scale is 3.5% off the printed scale, outside the 2% check.")
    expect(measureProvenance({ measure: { from: 'dxf_entities' } })).toBe('Measured from dxf entities.')
    expect(measureProvenance({ measure: { from: 'pdf_vector', scale_source: 'scale bar', scale_check: {} } })).toBe("Read from the PDF's vector lines using the printed scale bar.")
    expect(measureProvenance({ width_m: 1 })).toBeNull()
    expect(measureProvenance({ measure: {} })).toBeNull()
  })
})

describe('sourceProps', () => {
  it('drops the measure object, shown rows and geometry internals', () => {
    expect(sourceProps(door)).toEqual({ leaf: true })
    expect(sourceProps(wall)).toEqual({ style: 'fill' })
    expect(sourceProps(room)).toEqual({ labelled: true })
    expect(sourceProps({ conf: 0.8, width_m: 1 })).toEqual({ conf: 0.8 })
  })
})

it('builds an ask link for any item kind', () => {
  const params = new URLSearchParams(itemAskHref('plan / a', 'door', 'D 3').split('?')[1])
  expect(params.get('doc')).toBe('plan / a')
  expect(params.get('question')).toBe('Tell me about door D 3: its size and where it is.')
})
