// CONTRACT.md v1, sections 5.3 and 5.7. Coordinates are page-image pixels.
export type Bbox = [number, number, number, number]

export interface Document {
  doc_id: string
  source: string
  formats: string[]
  kind: 'raster' | 'pdf' | 'dxf' | 'dwg' | 'ifc' | 'svg'
  title: string
  pages: number
  licence: string
  credit: string
  heldout: boolean
}

export interface Answer {
  answer_id: string
  question: string
  doc_ids: string[]
  answer: { text_md: string; value: number | string | null; unit: string | null; confidence: number; abstained: boolean }
  citations: { n: number; doc_id: string; page: number; kind: 'region' | 'text' | 'element'; bbox_px: Bbox | null; item_ids: string[]; quote: string | null }[]
  evidence: {
    boxes: { item_id: string; page: number; bbox_px: Bbox; label: string }[]
    scene: { doc_id: string; highlight_item_ids: string[]; camera_target_item_id: string | null }
  }
  trace: { step: string; detail: string; ms: number; model: string | null; cost_usd: number }[]
  route: 'index' | 'planmap' | 'vlm' | 'hybrid'
  cost: { usd_total: number; calls: unknown[] }
  latency_ms: number
}
