import { useEffect, useRef, useState } from 'react'
import type { Point } from '../../lib/page-transform'

export type MarkupTool = 'pan' | 'marker' | 'pen'
export type Annotation = { id: string; page: number; tool: 'marker' | 'pen'; points: Point[]; width: number }
const storageKey = (docId: string) => `hologram:annotations:${docId}`

export function useAnnotations(docId: string, page: number) {
  const [state, setState] = useState<{ docId: string; marks: Annotation[] }>({ docId, marks: [] })
  const [warning, setWarning] = useState('')
  const marks = state.docId === docId ? state.marks : []
  const current = useRef({ docId, marks })
  current.current = { docId, marks }
  useEffect(() => {
    setWarning('')
    let saved: Annotation[] = []
    try {
      const value: unknown = JSON.parse(localStorage.getItem(storageKey(docId)) ?? '[]')
      if (Array.isArray(value)) saved = value.filter((mark): mark is Annotation =>
        !!mark && typeof mark.id === 'string' && Number.isInteger(mark.page) && ['pen', 'marker'].includes(mark.tool) &&
        Number.isFinite(mark.width) && mark.width > 0 && Array.isArray(mark.points) && mark.points.length > 0 &&
        mark.points.every((point: Point) => !!point && Number.isFinite(point.x) && Number.isFinite(point.y)))
    } catch { setWarning('Saved annotations could not be loaded on this device.') }
    current.current = { docId, marks: saved }
    setState({ docId, marks: saved })
  }, [docId])

  function update(change: (previous: Annotation[]) => Annotation[]) {
    if (current.current.docId !== docId) return
    const next = change(current.current.marks)
    current.current = { docId, marks: next }
    setState({ docId, marks: next })
    try { localStorage.setItem(storageKey(docId), JSON.stringify(next)); setWarning('') }
    catch { setWarning('Annotations are visible, but this device could not save them.') }
  }
  return {
    marks: marks.filter((mark) => mark.page === page), warning,
    add: (mark: Annotation) => update((previous) => [...previous, mark]),
    undo: () => update((previous) => {
      const last = previous.length - 1 - [...previous].reverse().findIndex((mark) => mark.page === page)
      return previous.filter((_, index) => index !== last)
    }),
    clear: () => update((previous) => previous.filter((mark) => mark.page !== page)),
  }
}

export function AnnotationLayer({ marks, draft }: { marks: Annotation[]; draft: Annotation | null }) {
  return <g className="drawing-annotations" aria-label="Saved page annotations">
    {[...marks, ...(draft ? [draft] : [])].map((mark) => {
      const first = mark.points[0], last = mark.points[mark.points.length - 1]
      return mark.tool === 'marker'
        ? <rect key={mark.id} data-annotation="marker" x={Math.min(first.x, last.x)} y={Math.min(first.y, last.y)} width={Math.max(1, Math.abs(last.x - first.x))} height={Math.max(1, Math.abs(last.y - first.y))} fill="#facc15" opacity=".4" />
        : <polyline key={mark.id} data-annotation="pen" points={mark.points.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#185440" strokeWidth={mark.width} strokeLinecap="round" strokeLinejoin="round" />
    })}
  </g>
}
