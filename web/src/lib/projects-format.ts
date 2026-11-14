import { cleanTitle } from './overview'
import type { ProjectDoc, ProjectRole } from './projects-api'

export const roleLabels: Record<ProjectRole, string> = {
  model: 'Model', plan: 'Plan', section: 'Section', elevation: 'Elevation', detail: 'Detail', schedule: 'Schedule',
  scan: 'Scan', photo: 'Photo', spec: 'Specification', revision: 'Revision', other: 'Other',
}

export const rolePlural: Record<ProjectRole, string> = {
  model: 'Models', plan: 'Plans', section: 'Sections', elevation: 'Elevations', detail: 'Details', schedule: 'Schedules',
  scan: 'Scans', photo: 'Photos', spec: 'Specifications', revision: 'Revisions', other: 'Other',
}

/** "19 hours ago", "Yesterday", or a short date. Never throws on a bad date. */
export function relativeTime(value: string | undefined, now = Date.now()): string {
  const time = value ? Date.parse(value) : NaN
  if (Number.isNaN(time)) return ''
  const minutes = Math.round((now - time) / 60_000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.round(hours / 24)
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  return new Date(time).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: new Date(time).getFullYear() === new Date(now).getFullYear() ? undefined : 'numeric' })
}

export const fileCount = (count: number) => `${count} ${count === 1 ? 'file' : 'files'}`

/** The short type tag shown on a file: IFC, PNG, DXF, PDF. */
export function typeTag(doc: Pick<ProjectDoc, 'kind' | 'formats'>): string {
  const format = doc.formats?.[0]
  return (format || doc.kind || 'file').toUpperCase().replace('JPEG', 'JPG')
}

export const docTitle = (doc: Pick<ProjectDoc, 'title'>) => cleanTitle(doc.title)

/** A file is still being read by the server. */
export const isReading = (doc: Pick<ProjectDoc, 'status'>) => !!doc.status && ['running', 'ingesting', 'pending', 'queued', 'processing'].includes(doc.status)
export const isFailed = (doc: Pick<ProjectDoc, 'status'>) => doc.status === 'failed'

export const thumbUrl = (doc: Pick<ProjectDoc, 'doc_id' | 'thumb_url'>) => doc.thumb_url || `/api/docs/${encodeURIComponent(doc.doc_id)}/files/page-1.thumb.png`

/** Value shown in a tile or table cell; a missing number stays missing. */
export const count = (value: number | null | undefined) => value == null ? '–' : new Intl.NumberFormat('en-GB').format(value)
export const area = (value: number | null | undefined) => value == null ? '–' : `${new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 }).format(value)} m²`

export const severityLabel = { high: 'High', medium: 'Medium', low: 'Low' } as const
