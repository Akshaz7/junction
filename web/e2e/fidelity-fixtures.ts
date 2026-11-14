import type { Answer, ChangeEntry, Comparison, Document } from '../src/lib/types'
import { makeDemoAnswer, demoDocument } from '../src/mock/handler'

// Entirely synthetic, served only by Playwright. No reference drawings or assets enter the app.
export const fidelityDocs: Document[] = [
  ...Array.from({ length: 10 }, (_, index) => ({ ...demoDocument, doc_id: index ? `demo__drawing-${index}` : demoDocument.doc_id,
    title: `${index ? `Drawing ${String(index + 1).padStart(2, '0')}` : 'Garden room'}.pdf — generated for demo`, source: 'Architecture', formats: ['pdf'], kind: 'pdf' as const })),
  ...['Structural', 'HVAC', 'Electrical', 'Contracts', 'Meeting minutes'].map((source, index) => ({ ...demoDocument,
    doc_id: `demo__folder-${index}`, title: `${source} — generated for demo`, source })),
]
export const fidelityQuestion = 'How many windows are in the garden room?'
export const fidelityAnswer: Answer = {
  ...makeDemoAnswer(fidelityQuestion),
  evidence: { ...makeDemoAnswer(fidelityQuestion).evidence, boxes: makeDemoAnswer(fidelityQuestion).evidence.boxes.slice(0, 1) },
  answer: { text_md: 'The garden room has **2 windows**, as drawn along its north wall. [1] Both are marked on the generated plan. [2]', value: 2, unit: 'count', confidence: 1, abstained: false },
  citations: [
    { n: 1, doc_id: demoDocument.doc_id, page: 1, kind: 'region', bbox_px: [100, 40, 180, 52], item_ids: ['window-001'], quote: 'The first window is on the north wall (generated for demo).' },
    { n: 2, doc_id: demoDocument.doc_id, page: 1, kind: 'text', bbox_px: [260, 40, 340, 52], item_ids: ['window-002'], quote: 'The second window is also on the north wall (generated for demo).' },
    { n: 3, doc_id: demoDocument.doc_id, page: 1, kind: 'text', bbox_px: [80, 130, 360, 175], item_ids: [], quote: 'Garden room; generated for demo.' },
  ],
}
export const fidelityFeed: ChangeEntry[] = Array.from({ length: 6 }, (_, index) => ({
  id: `demo-change-${index}`, type: index < 3 ? 'new_version' : 'new_document',
  doc_a: `${demoDocument.doc_id}@v1`, doc_b: `${demoDocument.doc_id}@v2`, created_at: '2026-11-02T12:00:00Z',
  summary: { doc_id: fidelityDocs[index].doc_id, title: fidelityDocs[index].title, n_changes: index < 3 ? 3 : undefined, generated_for_demo: true, headline: 'Generated comparison for the fidelity test.' },
}))
export const fidelityComparison: Comparison = {
  ...fidelityFeed[0], doc_id: demoDocument.doc_id, source: 'truth', generated_for_demo: true, image: { w: 440, h: 320 },
  v1: { label: 'Version 1', page_image: '/api/fidelity/previous.svg', thumb: '/api/fidelity/previous.svg' },
  v2: { label: 'Version 2', page_image: '/api/fidelity/current.svg', thumb: '/api/fidelity/current.svg' },
  changes: [
    { n: 1, change_id: 'demo-1', type: 'removed', kind: 'wall', sentence: 'The internal wall reads absent where it read present (generated for demo).', v1: { item_id: 'wall-001', bbox_px: [215, 46, 225, 260] }, v2: null },
    { n: 2, change_id: 'demo-2', type: 'added', kind: 'door', sentence: 'A door reads present where it read absent (generated for demo).', v1: null, v2: { item_id: 'door-001', bbox_px: [100, 245, 140, 265] } },
    { n: 3, change_id: 'demo-3', type: 'modified', kind: 'room', sentence: 'The label reads Garden room where it read Room (generated for demo).', v1: { item_id: 'room-001', bbox_px: [150, 130, 290, 170] }, v2: { item_id: 'room-001', bbox_px: [150, 130, 290, 170] } },
  ],
}
export function fidelityDrawing(previous = false) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="440" height="320" viewBox="0 0 440 320"><rect width="440" height="320" fill="white"/><path d="M60 46H380V260H60Z${previous ? 'M220 46V260' : ''}" fill="none" stroke="#1a1a1a" stroke-width="8"/><path d="M100 46H180M260 46H340" stroke="#666" stroke-width="10"/><text x="220" y="140" text-anchor="middle" font-family="Arial" font-size="18">${previous ? 'Room' : 'Garden room'}</text><text x="220" y="170" text-anchor="middle" font-family="Arial" font-size="12">generated for demo</text></svg>`
}
