import type { Bbox } from '../../lib/types'
export type MatchStatus = 'pending' | 'confirmed' | 'rejected'
export interface SymbolMatch { id: string; bbox: Bbox; score: number; status: MatchStatus; room: string | null }
export interface TaughtSymbol { id: string; doc_id: string; name: string; note: string; page: number; template_bbox: Bbox; matches: SymbolMatch[]; matcher_note?: string; summary: { found: number; confirmed: number; pending: number; rejected: number; rooms: Record<string, number> } }
export interface MarkupPin { id: string; doc_id: string; n: number; page: number; x: number; y: number; note: string }
export interface MarkupData { symbols: TaughtSymbol[]; pins: MarkupPin[]; suggestions: string[] }
export async function markupRequest<T>(docId: string, suffix = '', init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/docs/${encodeURIComponent(docId)}/markup${suffix}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    let message = `Labels could not be saved (${response.status}).`
    try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail } catch { /* Keep status. */ }
    throw new Error(message)
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}
