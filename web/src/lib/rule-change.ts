import type { ChangeFeedEntry } from './types'

function httpUrl(value?: string | null) {
  try {
    const url = new URL(value || '')
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null
  } catch { return null }
}

function timestamp(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

/** Rule updates are complete feed cards; they have no drawing comparison. */
export function ruleChangeCard(entry: ChangeFeedEntry) {
  if (entry.type !== 'rule_change') return null
  const summary = entry.summary
  return {
    id: entry.id,
    title: summary?.title?.trim() || 'Untitled rule source',
    url: httpUrl(summary?.url),
    detail: summary?.summary?.trim() || summary?.headline?.trim() || '',
    detectedAt: timestamp(summary?.detected_at) || timestamp(entry.created_at),
  }
}
