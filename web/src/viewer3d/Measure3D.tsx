/** 3D measuring tool: the same Distance / Area tool as the 2D viewer, on the model's surfaces. Points are world
 * points in scene metres (y up) from Viewer.pickPoint; distance is the straight 3D line, area is the polygon's
 * plan (x/z) area and perimeter. Esc cancels, Enter or double-click closes an area, Backspace removes a point. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Viewer } from './viewer';
import { formatM, formatM2 } from '../lib/measure';

export type P3 = [number, number, number];
export type Measure3DMode = 'distance' | 'area';

export function distance3(a: P3, b: P3): number { return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); }
export function planArea(points: P3[]): number {
  let sum = 0;
  for (let i = 0; i < points.length; i++) { const [x0, , z0] = points[i], [x1, , z1] = points[(i + 1) % points.length]; sum += x0 * z1 - x1 * z0; }
  return Math.abs(sum) / 2;
}
export function planPerimeter(points: P3[], closed: boolean): number {
  let sum = 0;
  for (let i = 0; i + 1 < points.length; i++) sum += Math.hypot(points[i + 1][0] - points[i][0], points[i + 1][2] - points[i][2]);
  if (closed && points.length > 2) sum += Math.hypot(points[0][0] - points.at(-1)![0], points[0][2] - points.at(-1)![2]);
  return sum;
}

export function useMeasure3D() {
  // One state object so add/close never read a stale `done` or `mode` (same pattern as the 2D useMeasure).
  const [st, setSt] = useState<{ mode: Measure3DMode | null; points: P3[]; cursor: P3 | null; done: boolean }>({ mode: null, points: [], cursor: null, done: false });
  const { mode, points, cursor, done } = st;
  const start = useCallback((next: Measure3DMode) => setSt({ mode: next, points: [], cursor: null, done: false }), []);
  const stop = useCallback(() => setSt({ mode: null, points: [], cursor: null, done: false }), []);
  const add = useCallback((p: P3) => setSt((s) => {
    if (!s.mode) return s;
    if (s.done) return { ...s, points: [p], done: false };
    const next = [...s.points, p];
    return { ...s, points: next, done: s.mode === 'distance' && next.length >= 2 };
  }), []);
  const undo = useCallback(() => setSt((s) => ({ ...s, points: s.points.slice(0, -1), done: false })), []);
  const close = useCallback(() => setSt((s) => (s.mode === 'area' && s.points.length >= 3 ? { ...s, done: true } : s)), []);
  const setCursor = useCallback((p: P3 | null) => setSt((s) => (s.mode ? { ...s, cursor: p } : s)), []);
  const result = useMemo(() => {
    if (!done) return null;
    if (mode === 'distance' && points.length >= 2) return { distanceM: distance3(points[0], points[1]) };
    if (mode === 'area' && points.length >= 3) return { areaM2: planArea(points), perimeterM: planPerimeter(points, true) };
    return null;
  }, [done, mode, points]);
  useEffect(() => {
    if (!mode) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); stop(); }
      else if (event.key === 'Enter' && mode === 'area') { event.preventDefault(); close(); }
      else if (event.key === 'Backspace' && !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) { event.preventDefault(); undo(); }
    }
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [mode, stop, close, undo]);
  return { mode, points, cursor: done ? null : cursor, done, result, start, stop, add, undo, close, move: setCursor };
}
export type Measure3D = ReturnType<typeof useMeasure3D>;

export function measure3DStatus(m: Measure3D): string {
  if (m.result?.distanceM != null) return `Distance ${formatM(m.result.distanceM)}`;
  if (m.result?.areaM2 != null) return `Area ${formatM2(m.result.areaM2)} · perimeter ${formatM(m.result.perimeterM ?? 0)}`;
  return m.mode === 'area' ? 'Click corners on the model, double-click or Enter to close · Esc to cancel' : 'Click two points on the model · Esc to cancel';
}

/** Lines, dots and the value label, re-projected every frame so they follow the camera. */
export function Measure3DOverlay({ viewer, measure }: { viewer: Viewer | null; measure: Measure3D }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!measure.mode) return;
    let frame = 0;
    const loop = () => { setTick((n) => (n + 1) % 1e6); frame = requestAnimationFrame(loop); };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [measure.mode]);
  if (!viewer || !measure.mode) return null;
  const pts = measure.cursor ? [...measure.points, measure.cursor] : measure.points;
  const screen = pts.map((p) => viewer.projectPoint(p));
  const closed = measure.mode === 'area' && measure.done;
  const path = screen.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ') + (closed ? ' Z' : '');
  const live = measure.result
    ? (measure.result.distanceM != null ? formatM(measure.result.distanceM) : formatM2(measure.result.areaM2 ?? 0))
    : measure.mode === 'distance' && pts.length === 2 ? formatM(distance3(pts[0], pts[1]))
    : measure.mode === 'area' && pts.length >= 3 ? formatM2(planArea(pts)) : null;
  const anchor = screen.length ? (measure.mode === 'distance' && screen.length >= 2
    ? { x: (screen[0].x + screen[1].x) / 2, y: (screen[0].y + screen[1].y) / 2 }
    : { x: screen.reduce((s, p) => s + p.x, 0) / screen.length, y: screen.reduce((s, p) => s + p.y, 0) / screen.length }) : null;
  return <svg className="viewer3d-measure" data-testid="measure-3d" aria-hidden="true">
    {screen.length > 1 && <path d={path} className={closed ? 'is-closed' : ''} />}
    {screen.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={4} />)}
    {live && anchor && <g transform={`translate(${anchor.x},${anchor.y - 14})`}><rect x={-34} y={-11} width={68} height={22} rx={6} /><text textAnchor="middle" dy="4">{live}</text></g>}
  </svg>;
}
