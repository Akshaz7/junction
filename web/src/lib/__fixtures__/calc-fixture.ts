import type { Calculation, Reasoning } from '../types'

const doc = 'scan-1'
/** A scanned floor plan: counts read by a detector, scale from door widths. All figures are generated for demo. */
export const scanCalc: Calculation = {
  method: { id: 'scale.door_prior', label: 'Scale from door widths (typical 0.9 m leaf)', why_chosen: 'no printed scale or dimension string was found on the sheet', alternatives: [{ id: 'scale.printed', value: undefined, rejected_because: 'no scale text detected' }, { id: 'scale.dimension_string', label: 'Dimension strings', rejected_because: 'none readable at this resolution' }] },
  formula: 'doors = number of detections with score ≥ 0.50 after merging overlaps (IoU ≥ 0.60)',
  steps: [
    { id: 's1', label: 'Image size', expr: '1,240 px × 1,754 px at 150 dpi', value: 2175, unit: 'px', note: 'read from the file header', inputs: [{ name: 'file', value: 'scan-1.png', unit: '', source: { doc_id: doc, page: 1, field: 'image header' } }] },
    { id: 's2', label: 'Scale', expr: '0.9 m ÷ 31.0 px', value: 0.02903, unit: 'm/px', note: 'median of 9 door widths; spread 3.1%',
      inputs: [
        { name: 'door 3 width', value: 31, unit: 'px', source: { doc_id: doc, page: 1, item_id: 'door-3', bbox: [100, 200, 131, 230], crop: '/crops/door-3.png' } },
        { name: 'standard door leaf', value: 0.9, unit: 'm', source: { kind: 'rule', field: 'typical single door leaf' } },
      ] },
    { id: 's3', label: 'Doors detected', expr: '14 detections − 3 below threshold', value: 11, unit: 'count', note: 'score threshold 0.50, median score 0.81',
      inputs: [{ name: 'detections', value: 14, unit: 'count', source: { doc_id: doc, page: 1, step_id: 'detector' } }, { name: 'below threshold', value: 3, unit: 'count', source: { doc_id: doc, page: 1, step_id: 'detector' } }] },
    { id: 's4', label: 'Walls detected', expr: '44 segments − 4 merged duplicates', value: 40, unit: 'count', inputs: [] },
  ],
  rows: Array.from({ length: 11 }, (_, i) => ({ item_id: `door-${i + 1}`, label: `Door ${i + 1}`, values: { width_px: 28 + (i % 5) * 2, score: Math.round((0.95 - i * 0.03) * 100) / 100 }, source: { doc_id: doc, page: 1, item_id: `door-${i + 1}` } })),
  result: { value: 11, unit: 'count', rounded_as: 'whole number' },
  checks: [{ method: 'second look at the image', value: 11, agrees: true, diff_pct: 0 }, { method: 'wall length ÷ door count', value: 12, agrees: false, diff_pct: 8.3 }],
  margin: { value: 1, unit: 'count', pct: 9.1, why: 'one door below the score threshold could not be confirmed', sources: ['detector score distribution'] },
}

export const areaCalc: Calculation = {
  formula: 'net area = Σ(room outline areas) − Σ(excluded)',
  steps: [{ id: 's1', label: 'Rooms summed', expr: '16.5 + 12.2 + 9.8', value: 38.5, unit: 'm2', inputs: [{ name: 'Kitchen', value: 16.5, unit: 'm2', source: { doc_id: 'plan', page: 1, item_id: 'room-1' } }] }],
  rows: [
    { item_id: 'room-1', label: 'Kitchen', values: { area_m2: 16.5 }, source: { doc_id: 'plan', page: 1, item_id: 'room-1' } },
    { item_id: 'room-2', label: 'Living room', values: { area_m2: 12.2 }, source: { doc_id: 'plan', page: 1, item_id: 'room-2' } },
    { item_id: 'room-3', label: 'Bedroom 2', values: { area_m2: 9.8 }, source: { doc_id: 'plan', page: 1, item_id: 'room-3' } },
  ],
  result: { value: 38.5, unit: 'm2', rounded_as: '1 decimal' },
  checks: [{ method: 'printed labels', value: 38.4, agrees: true, diff_pct: 0.3 }],
  margin: { value: 0.4, unit: 'm2', pct: 1, why: 'outline traced at ±0.5 px', sources: [] },
}

export const scanReasoning: Reasoning = {
  steps: [{ kind: 'found', title: 'Found', text: '40 walls and 11 doors on the scanned drawing', cite: 1 }],
  confidence: {
    label: 'Estimate', pct: 65, reason: 'The result was read from the drawing image by a model.', improve: 'Upload a CAD file to make it exact.',
    factors: [{ label: 'Read from a scan, no CAD source', delta: 0, base: true, note: 'starting point 70%' }, { label: 'Second look agrees', delta: 8 }, { label: 'Wall-length cross-check differs 8.3%', delta: -13 }],
  },
  margin: scanCalc.margin,
  calc: scanCalc,
  graph_path: [{ label: 'scan-1.png', kind: 'file' }, { label: 'Page 1', kind: 'sheet' }, { label: 'Door 3', kind: 'item', item_id: 'door-3', relation: 'width measured' }, { label: '0.02903 m/px', kind: 'scale', relation: 'gives' }],
}

const ifcSrc = (id: string) => ({ doc_id: 'model', item_id: id, artifact: 'IfcDoor' })
/** A scan whose sheet prints its scale: a different method with different step names. */
export const scanPrintedCalc: Calculation = {
  method: { id: 'scale.printed', label: 'Printed scale 1:100 read from the title block', why_chosen: 'a printed scale was found and agrees with the sheet size', alternatives: [{ id: 'scale.door_prior', label: 'Scale from door widths', value: 0.0261, unit: 'm/px', rejected_because: 'less direct than a printed scale; differs 3.2%' }] },
  formula: 'length m = pixels × (0.0254 m/in ÷ 150 px/in) × 100',
  steps: [
    { id: 'p1', label: 'Printed scale', expr: '1:100', value: 100, unit: '', inputs: [{ name: 'title block text', value: '1:100', unit: '', source: { doc_id: 'scan-2', page: 1, text: 'SCALE 1:100' } }] },
    { id: 'p2', label: 'Metres per pixel', expr: '0.0254 ÷ 150 × 100', value: 0.016933, unit: 'm/px', inputs: [] },
    { id: 'p3', label: 'Wall length', expr: '1,180 px × 0.016933 m/px', value: 19.98, unit: 'm', inputs: [] },
  ],
  rows: [], checks: [],
  result: { value: 19.98, unit: 'm', rounded_as: '2 decimals' },
  margin: { value: 0.1, unit: 'm', pct: 0.5, why: 'one pixel of edge uncertainty per wall end', sources: [] },
}
export const ifcCountCalc: Calculation = {
  method: { id: 'count.ifc_elements', label: 'Count of IfcDoor elements', why_chosen: 'the model lists doors directly, so counting needs no measurement', alternatives: [{ id: 'count.geometry', value: 77, rejected_because: 'same result; geometry only confirms it' }] },
  formula: 'count = number of IfcDoor elements',
  steps: [{ id: 'c1', label: 'Elements of the requested kind', expr: 'Σ 1 over 3 storeys: 30 + 25 + 22', value: 77, unit: 'count', inputs: [{ name: 'ground floor', value: 30, unit: 'count', source: ifcSrc('d1') }] }],
  rows: Array.from({ length: 3 }, (_, i) => ({ item_id: `d${i}`, label: `Storey ${i + 1}`, values: { count: [30, 25, 22][i] }, source: ifcSrc(`d${i}`) })),
  checks: [{ method: 'geometry recount', value: 77, agrees: true, diff_pct: 0 }],
  result: { value: 77, unit: 'count', rounded_as: 'whole number' },
  margin: { value: 0, unit: 'count', pct: 0, why: 'counted from the model, not estimated', sources: [] },
}
export const ifcWallAreaCalc: Calculation = {
  method: { id: 'wallarea.geometry', label: 'Measured side faces minus opening cuts', why_chosen: 'model quantities were missing for most walls, so areas come from geometry', alternatives: [{ id: 'wallarea.quantity', value: 940.8, unit: 'm2', rejected_because: 'only 38 of 44 walls carry a NetSideArea' }] },
  formula: 'net = Σ(gross side faces) − Σ(opening cuts)',
  steps: [
    { id: 'w1', label: 'Gross side faces', expr: '302.4 + 302.4 + 74.1 + …', value: 1296.1, unit: 'm2', inputs: [] },
    { id: 'w2', label: 'Openings cut out', expr: '80.7 + 80.7 + 5.9 + …', value: 319.6, unit: 'm2', inputs: [] },
    { id: 'w3', label: 'Net', expr: '1,296.1 − 319.6', value: 976.5, unit: 'm2', inputs: [] },
  ],
  rows: [{ item_id: 'f1', label: 'Floor 1', values: { gross_m2: 302.4, openings_m2: 80.7, area_m2: 221.7 }, source: { doc_id: 'model' } }],
  checks: [{ method: 'model quantity', value: 940.8, agrees: false, diff_pct: 3.8 }],
  result: { value: 976.5, unit: 'm2', rounded_as: '1 decimal' },
  margin: { value: 0.08, unit: 'm2', pct: 0.01, why: 'orientation allowance', sources: ['wall geometry'] },
}
