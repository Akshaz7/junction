import type { SceneCommand } from '../viewer3d/commands'

// CONTRACT.md v3.1. Coordinates are page-image pixels.
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

export interface IngestStatus {
  status: 'none' | 'running' | 'ready' | 'partial' | 'failed'
  stages: { stage: string; ok: boolean; s: number }[]
  detail: string
}

export interface UploadReceipt {
  doc_id: string
  status: 'ingesting' | 'stored'
  detail: string
}

export interface Answer {
  answer_id: string
  question: string
  doc_ids: string[]
  answer: { text_md: string; value: number | string | null; unit: string | null; confidence: number; abstained: boolean }
  citations: { n: number; doc_id: string; page: number; kind: 'region' | 'text' | 'element'; bbox_px: Bbox | null; item_ids: string[]; quote: string | null }[]
  evidence: {
    boxes: { item_id: string; page: number; bbox_px: Bbox; label: string }[]
    scene: { doc_id: string; highlight_item_ids: string[]; camera_target_item_id: string | null; commands?: readonly SceneCommand[] }
  }
  trace: { step: string; detail: string; ms: number; model: string | null; cost_usd: number; stub?: boolean }[]
  route: 'index' | 'planmap' | 'vlm' | 'hybrid'
  cost: { usd_total: number; calls: unknown[] }
  latency_ms: number
}

export type Citation = Answer['citations'][number]
export type TraceStep = Answer['trace'][number]

export interface PlanMap {
  doc_id: string
  page: number
  items: { item_id: string; bbox_px: Bbox | null; tag?: string; props?: { tag?: string } }[]
}

export interface SavedChat {
  id: string
  doc_id: string | null
  messages: { id: string; role: string; content: string; answer: Answer | null }[]
}

export interface ChangeEntry {
  id: string
  type: 'new_version' | 'new_document'
  doc_a: string | null
  doc_b: string
  created_at: string
  summary: { doc_id?: string; title?: string; n_changes?: number; headline?: string; generated_for_demo?: boolean }
}

export interface Comparison extends ChangeEntry {
  doc_id: string
  generated_for_demo: boolean
  source: string
  image: { w: number; h: number }
  v1: { label: string; page_image: string; thumb: string }
  v2: { label: string; page_image: string; thumb: string }
  changes: {
    n: number; change_id: string; type: 'added' | 'removed' | 'modified'; kind: string; sentence: string
    v1: { item_id: string; bbox_px: Bbox | null } | null
    v2: { item_id: string; bbox_px: Bbox | null } | null
  }[]
}
