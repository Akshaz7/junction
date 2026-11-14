import type { AdvisorCard } from '../viewer3d/advisor'
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

export interface ReasoningStep { kind: 'found' | 'measured' | 'checked' | 'calculated' | 'read'; title: string; text: string; cite?: number | null; ok?: boolean | null }
export interface GraphPathStep { from_id?: string; to_id?: string; from_label: string; edge_kind: string; to_label: string; method?: string; confidence?: number }
export interface Reasoning {
  steps: ReasoningStep[]
  graph_path?: GraphPathStep[] | null
  confidence: { label: 'Verified' | 'Cross-checked' | 'Estimate'; pct: number; reason: string; improve?: string | null }
}

export interface Answer {
  answer_id: string
  question: string
  doc_ids: string[]
  answer: { text_md: string; value: number | string | Record<string, number> | null; unit: string | null; confidence: number; abstained: boolean }
  citations: { n: number; doc_id: string; page: number; kind: 'region' | 'text' | 'element'; bbox_px: Bbox | null; item_ids: string[]; quote: string | null; item_kind?: string | null }[]
  evidence: {
    boxes: { item_id: string; page: number; bbox_px: Bbox; label: string; kind?: string | null }[]
    scene: { doc_id: string; highlight_item_ids: string[]; camera_target_item_id: string | null; commands?: readonly SceneCommand[]; open?: '3d' | 'ar' }
  }
  trace: { step: string; detail: string; ms: number; model: string | null; cost_usd: number; stub?: boolean }[]
  route: 'index' | 'planmap' | 'vlm' | 'hybrid'
  cost: { usd_total: number; calls: unknown[] }
  latency_ms: number
  /** Edit checks for a hide/remove command in chat (severity, checked rules). */
  advisor_cards?: AdvisorCard[]
  /** How the answer was found and how sure we are (backend, optional). */
  reasoning?: Reasoning
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
  /** Set while a question in this chat is still being answered (late joiners catch up from it). */
  active?: { question: string; statuses: string[]; traces: TraceStep[]; text?: string }
}

export interface ChangeEntry {
  id: string
  type: 'new_version' | 'new_document'
  doc_a: string | null
  doc_b: string
  created_at: string
  summary: { doc_id?: string; title?: string; n_changes?: number; headline?: string; generated_for_demo?: boolean; source?: string; series_id?: string; version_a?: number; version_b?: number
    /** Any two versions of a drawing compare: version numbers of this pair and the id prefix for `<prefix><a>-<b>`. */
    index_a?: number; index_b?: number; pair_prefix?: string
    /** Saved 3D edits (design versions): generated from edits, not an issued drawing. */
    edited?: boolean; generated?: string; counts?: { removed: number; added: number; moved: number; material: number } }
}

export interface RuleChangeEntry {
  id: string
  type: 'rule_change'
  doc_a: null
  doc_b: null
  created_at?: string | null
  summary?: {
    kind?: 'rule_change'; source?: string; url?: string | null; rule_ids?: string[]
    title?: string | null; summary?: string | null; headline?: string | null
    detected_at?: string | null; importance?: string | null
  } | null
}

export type ChangeFeedEntry = ChangeEntry | RuleChangeEntry

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
    /** Design-version diffs: exact item change (removed | added | moved | material), with the item's id and tag. */
    edit?: boolean; action?: 'removed' | 'added' | 'moved' | 'material'; item_id?: string; tag?: string | null
  }[]
  /** Design-version comparisons: counts over the whole document and every changed item id (for 3D/AR highlight). */
  edited?: boolean; counts?: { removed: number; added: number; moved: number; material: number }; item_ids?: string[]
}
