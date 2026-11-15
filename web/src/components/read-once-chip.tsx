import { useEffect, useState } from 'react'
import { workspaceApi } from '../lib/api'
import { formatCost } from './answer-card'

/** Seconds spent reading the drawing: the sum of its recorded ingest stages. */
export function readSeconds(stages: { s?: number }[] | undefined): number | null {
  const values = (stages ?? []).map((stage) => stage.s).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  return values.length ? values.reduce((a, b) => a + b, 0) : null
}

export function readOnceLabel(cost: number | null | undefined, seconds: number | null): string | null {
  if (typeof cost !== 'number' || !Number.isFinite(cost)) return null
  return `Read once: ${formatCost(cost)}${seconds === null ? '' : ` · ${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`}`
}

/** What reading this drawing once cost; every later answer is plain code over the result. Shown only when the server recorded it. */
export function ReadOnceChip({ docId }: { docId: string }) {
  const [label, setLabel] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    setLabel(null)
    workspaceApi.getIngestStatus(docId, controller.signal).then((state) => {
      if (!controller.signal.aborted && state.status === 'ready') setLabel(readOnceLabel(state.cost_usd, readSeconds(state.stages)))
    }).catch(() => undefined)
    return () => controller.abort()
  }, [docId])
  if (!label) return null
  return <span className="read-once-chip" data-testid="read-once" title="One-time cost of reading this drawing into a structured plan map. Questions after that are answered by code over it.">{' · '}{label}</span>
}
