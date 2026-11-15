/**
 * Measure tool: distance (two clicks) and area (polygon, close with double-click / Enter).
 *
 * - `useMeasure(mPerPx: number | null = null)` holds the tool state. mPerPx is the page scale
 *   (metres per page pixel); with null, `result` is null and nothing is invented.
 *   Distance: after 2 points the measurement is complete; a 3rd add() starts a new one.
 *   Area: points accumulate; close() finishes (needs ≥3 points); the next add() starts a new polygon.
 *   `cursor` is reported as null once a measurement is complete, so the layer draws the final shape.
 *   The viewer wires clicks → add(snapPoint(...)), pointer move → move(), dblclick/Enter → close(),
 *   Backspace → undo(), Escape → stop().
 * - `<MeasureLayer>` renders INSIDE the viewer's page-pixel `<svg viewBox="0 0 W H">`;
 *   pointer-events none, non-scaling strokes, label font 13/scale.
 */
import { useCallback, useMemo, useState } from 'react'
import type { JSX } from 'react'
import { distanceM, formatM, formatM2, perimeterM, polygonAreaM2, type Pt } from '../../lib/measure'
import './measure-layer.css'

export type MeasureMode = 'distance' | 'area'
export interface MeasureResult { distanceM?: number; areaM2?: number; perimeterM?: number }

export const NO_SCALE_LABEL = 'No scale on this drawing'

export function MeasureLayer({ mode, points, cursor, mPerPx, scale }: { mode: MeasureMode; points: Pt[]; cursor: Pt | null; mPerPx: number | null; scale: number }): JSX.Element | null {
  if (!points.length) return null
  const s = Math.max(scale, 0.001)
  const font = 13 / s
  const r = 4 / s
  const hasScale = typeof mPerPx === 'number' && Number.isFinite(mPerPx) && mPerPx > 0
  const live: Pt[] = mode === 'distance'
    ? (points.length >= 2 ? points.slice(0, 2) : cursor ? [points[0], cursor] : points)
    : (cursor ? [...points, cursor] : points)
  const closedArea = mode === 'area' && !cursor && points.length >= 3

  let label: string[] = []
  let anchor: Pt = live[live.length - 1]
  if (mode === 'distance' && live.length === 2) {
    anchor = [(live[0][0] + live[1][0]) / 2, (live[0][1] + live[1][1]) / 2]
    label = [hasScale ? formatM(distanceM(live[0], live[1], mPerPx)) : NO_SCALE_LABEL]
  } else if (mode === 'area' && live.length >= 2) {
    anchor = live.length >= 3 ? centroid(live) : [(live[0][0] + live[1][0]) / 2, (live[0][1] + live[1][1]) / 2]
    if (!hasScale) label = [NO_SCALE_LABEL]
    else if (live.length >= 3) label = [formatM2(polygonAreaM2(live, mPerPx)), `perimeter ${formatM(perimeterM(live, mPerPx, true))}`]
    else label = [formatM(perimeterM(live, mPerPx, false))]
  }

  const path = live.map((p) => `${p[0]},${p[1]}`).join(' ')
  return <g className={`measure-layer is-${mode}`} data-mode={mode} pointerEvents="none" aria-label={label.length ? `Measurement: ${label.join(', ')}` : 'Measurement'}>
    {mode === 'area' && live.length >= 3
      ? <polygon className={`measure-shape${closedArea ? ' is-closed' : ''}`} points={path} vectorEffect="non-scaling-stroke" />
      : <polyline className="measure-line" points={path} vectorEffect="non-scaling-stroke" />}
    {live.map((p, i) => <circle key={i} className={`measure-dot${p === cursor ? ' is-cursor' : ''}`} cx={p[0]} cy={p[1]} r={r} vectorEffect="non-scaling-stroke" />)}
    {label.length > 0 && <text className={`measure-label${hasScale ? '' : ' is-unscaled'}`} x={anchor[0]} y={anchor[1] - font * (label.length - 0.4)} fontSize={font} textAnchor="middle">
      {label.map((line, i) => <tspan key={i} x={anchor[0]} dy={i ? font * 1.2 : 0}>{line}</tspan>)}
    </text>}
  </g>
}

function centroid(pts: Pt[]): Pt {
  let x = 0, y = 0
  for (const p of pts) { x += p[0]; y += p[1] }
  return [x / pts.length, y / pts.length]
}

interface State { mode: MeasureMode | null; points: Pt[]; cursor: Pt | null; done: boolean }
const EMPTY: State = { mode: null, points: [], cursor: null, done: false }

export function useMeasure(mPerPx: number | null = null) {
  const [st, setSt] = useState<State>(EMPTY)
  const start = useCallback((mode: MeasureMode) => setSt({ mode, points: [], cursor: null, done: false }), [])
  const stop = useCallback(() => setSt(EMPTY), [])
  const clear = useCallback(() => setSt((s) => ({ ...s, points: [], cursor: null, done: false })), [])
  const add = useCallback((p: Pt) => setSt((s) => {
    if (!s.mode) return s
    if (s.done) return { ...s, points: [p], done: false }
    const points = [...s.points, p]
    return { ...s, points, done: s.mode === 'distance' && points.length >= 2 }
  }), [])
  const move = useCallback((p: Pt | null) => setSt((s) => (s.mode ? { ...s, cursor: p } : s)), [])
  const undo = useCallback(() => setSt((s) => (s.points.length ? { ...s, points: s.points.slice(0, -1), done: false } : s)), [])
  const close = useCallback(() => setSt((s) => (s.mode === 'area' && s.points.length >= 3 ? { ...s, done: true } : s)), [])

  const result = useMemo<MeasureResult | null>(() => {
    if (!st.done || !(typeof mPerPx === 'number' && mPerPx > 0)) return null
    if (st.mode === 'distance') return { distanceM: distanceM(st.points[0], st.points[1], mPerPx) }
    if (st.mode === 'area') return { areaM2: polygonAreaM2(st.points, mPerPx), perimeterM: perimeterM(st.points, mPerPx, true) }
    return null
  }, [st, mPerPx])

  return { mode: st.mode, points: st.points, cursor: st.done ? null : st.cursor, done: st.done, start, stop, add, move, undo, close, clear, result }
}
