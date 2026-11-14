/**
 * Pure maths for the sheet compare canvas (seam, boxes, zoom, pan, thumbnails).
 * No DOM here, so every rule can be tested without a browser.
 *
 * Coordinates:
 *  - "world" = fractions of the sheet, (0,0) top-left to (1,1) bottom-right.
 *  - "screen" = CSS px inside the canvas viewport.
 *  - A View is the zoom `s` (1 = sheet fitted in the canvas) and the world point (cx, cy) shown at the viewport centre.
 */
export type Bbox = [number, number, number, number]
export type Size = { w: number; h: number }
export type View = { s: number; cx: number; cy: number }
export type Rect = { left: number; top: number; width: number; height: number }

export const MIN_SCALE = 0.25
export const MAX_SCALE = 12
export const ZOOM_STEPS = [25, 50, 75, 100, 150, 200, 300, 400, 600, 800, 1200]
export const THUMB_W = 118
export const THUMB_H = 68
export const THUMB_MAX_ZOOM = 900
export const MIN_BOX_PX = 9
export const SHEET_MARGIN = 10
/** Focusing a change never zooms past this, so small boxes keep their surroundings and the page raster stays sharp. */
export const REGION_MAX_SCALE = 5

export const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
export const FIT_VIEW: View = { s: 1, cx: 0.5, cy: 0.5 }

/** Seam position, in percent of the canvas width, for a pointer at clientX. Never leaves 0..100. */
export function seamFromPointer(clientX: number, left: number, width: number): number {
  if (!(width > 0)) return 50
  return Math.round(clamp((clientX - left) / width * 100, 0, 100) * 10) / 10
}

/** Keyboard on the seam: arrows 1 point (shift 10), Page keys 10, Home 0, End 100. Null when the key is not for the seam. */
export function nudgeSeam(seam: number, key: string, shift = false): number | null {
  const step = shift ? 10 : 1
  switch (key) {
    case 'ArrowLeft': case 'ArrowDown': return clamp(seam - step, 0, 100)
    case 'ArrowRight': case 'ArrowUp': return clamp(seam + step, 0, 100)
    case 'PageDown': return clamp(seam - 10, 0, 100)
    case 'PageUp': return clamp(seam + 10, 0, 100)
    case 'Home': return 0
    case 'End': return 100
    default: return null
  }
}

/** Size of the sheet at zoom 1: fits the canvas with a 10 px side margin, any aspect ratio. */
export function fitSheet(viewport: Size, sheet: Size, margin = SHEET_MARGIN): Size {
  if (!(viewport.w > 0 && viewport.h > 0 && sheet.w > 0 && sheet.h > 0)) return { w: 0, h: 0 }
  const scale = Math.min((viewport.w - margin * 2) / sheet.w, (viewport.h - margin * 2) / sheet.h)
  const k = Math.max(scale, 0.0001)
  return { w: sheet.w * k, h: sheet.h * k }
}

export function worldToScreen(u: number, v: number, view: View, fit: Size, viewport: Size) {
  return { x: viewport.w / 2 + (u - view.cx) * fit.w * view.s, y: viewport.h / 2 + (v - view.cy) * fit.h * view.s }
}
export function screenToWorld(x: number, y: number, view: View, fit: Size, viewport: Size) {
  return { u: view.cx + (x - viewport.w / 2) / (fit.w * view.s), v: view.cy + (y - viewport.h / 2) / (fit.h * view.s) }
}

/** CSS transform for the sheet layer (element laid out at the fitted size, origin top-left). */
export function sheetTransform(view: View, fit: Size, viewport: Size) {
  const origin = worldToScreen(0, 0, view, fit, viewport)
  return { x: origin.x, y: origin.y, scale: view.s }
}

export function clampView(view: View): View {
  return { s: clamp(view.s, MIN_SCALE, MAX_SCALE), cx: clamp(view.cx, 0, 1), cy: clamp(view.cy, 0, 1) }
}

/** Drag the sheet by (dx, dy) screen px. */
export function panView(view: View, dx: number, dy: number, fit: Size): View {
  if (!(fit.w > 0 && fit.h > 0)) return view
  return clampView({ ...view, cx: view.cx - dx / (fit.w * view.s), cy: view.cy - dy / (fit.h * view.s) })
}

/** Change zoom while the world point under `anchor` (screen px) stays put. */
export function zoomAt(view: View, s: number, anchor: { x: number; y: number }, fit: Size, viewport: Size): View {
  const next = clamp(s, MIN_SCALE, MAX_SCALE)
  if (!(fit.w > 0 && fit.h > 0)) return { ...view, s: next }
  const { u, v } = screenToWorld(anchor.x, anchor.y, view, fit, viewport)
  return clampView({ s: next, cx: u - (anchor.x - viewport.w / 2) / (fit.w * next), cy: v - (anchor.y - viewport.h / 2) / (fit.h * next) })
}

/** Next zoom stop (percent) above or below the current value. */
export function stepZoom(percent: number, direction: 1 | -1): number {
  const now = Math.round(percent)
  if (direction > 0) return ZOOM_STEPS.find((z) => z > now) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]
  return [...ZOOM_STEPS].reverse().find((z) => z < now) ?? ZOOM_STEPS[0]
}

/** Box position on screen. Boxes smaller than 9 px grow around their centre; the stroke and badge are drawn by CSS at fixed px. */
export function boxRect(bbox: Bbox, sheet: Size, view: View, fit: Size, viewport: Size, minPx = MIN_BOX_PX): Rect {
  const a = worldToScreen(bbox[0] / sheet.w, bbox[1] / sheet.h, view, fit, viewport)
  const b = worldToScreen(bbox[2] / sheet.w, bbox[3] / sheet.h, view, fit, viewport)
  const width = Math.max(Math.abs(b.x - a.x), minPx), height = Math.max(Math.abs(b.y - a.y), minPx)
  const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2
  return { left: cx - width / 2, top: cy - height / 2, width, height }
}

/** True when the bbox has real, ordered, finite extent inside a positive sheet. */
export function usableBox(bbox: readonly number[] | null | undefined, sheet: Size): bbox is Bbox {
  return !!bbox && bbox.length === 4 && bbox.every(Number.isFinite) && bbox[2] > bbox[0] && bbox[3] > bbox[1] && sheet.w > 0 && sheet.h > 0
}

/** View that shows a region large and centred (fills `fill` of the canvas), never zooming out below fit. */
export function regionView(bbox: Bbox, sheet: Size, fit: Size, viewport: Size, fill = 0.6): View {
  if (!(fit.w > 0 && fit.h > 0)) return FIT_VIEW
  // Tiny regions keep some context: at least 5 % of the sheet width.
  const rw = Math.max((bbox[2] - bbox[0]) / sheet.w, 0.05)
  const rh = Math.max((bbox[3] - bbox[1]) / sheet.h, 0.05 * fit.w / fit.h)
  const s = Math.min(fill * viewport.w / (rw * fit.w), fill * viewport.h / (rh * fit.h))
  return clampView({ s: clamp(s, 1, REGION_MAX_SCALE), cx: (bbox[0] + bbox[2]) / 2 / sheet.w, cy: (bbox[1] + bbox[3]) / 2 / sheet.h })
}

export const lerpView = (a: View, b: View, t: number): View => ({ s: a.s + (b.s - a.s) * t, cx: a.cx + (b.cx - a.cx) * t, cy: a.cy + (b.cy - a.cy) * t })
export const easeInOut = (t: number) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2

/**
 * Reading thumbnail: the full sheet image drawn `zoom` px wide, shifted so the change sits in the middle of the 118x68 frame.
 * zoom = min(118 / (w * 1.5), 68 * aspect / (h * 1.5), 900) where w, h are the region as sheet fractions and aspect = sheet w / h.
 */
export function thumbLayout(bbox: Bbox, sheet: Size, frame: Size = { w: THUMB_W, h: THUMB_H }) {
  const aspect = sheet.w / sheet.h
  const x1 = bbox[0] / sheet.w, x2 = bbox[2] / sheet.w, y1 = bbox[1] / sheet.h, y2 = bbox[3] / sheet.h
  const w = Math.max(x2 - x1, 1e-6), h = Math.max(y2 - y1, 1e-6)
  const zoom = Math.min(frame.w / (w * 1.5), frame.h * aspect / (h * 1.5), THUMB_MAX_ZOOM)
  const height = zoom / aspect
  return { zoom, width: zoom, height, left: frame.w / 2 - (x1 + x2) / 2 * zoom, top: frame.h / 2 - (y1 + y2) / 2 * height }
}

/** "Version 5 · 2 Nov 2026" becomes "Version 5". */
export function shortVersion(label: string | undefined | null): string {
  const text = (label || '').trim()
  if (!text) return 'Version'
  return text.split(/\s[·|]\s/)[0].trim() || text
}

/** The date part of a version label, for a tooltip. */
export function versionDate(label: string | undefined | null): string {
  const parts = (label || '').split(/\s[·|]\s/)
  return parts.length > 1 ? parts.slice(1).join(' · ').trim() : ''
}

/** Opening seam positions: starts closed at 0, then slides to 50 and idles. */
export const OPEN_SEAM_FROM = 0
export const OPEN_SEAM_TO = 50

/** Min colour channel helper for the overlay tint (hex "#rrggbb" or "#rgb"). Falls back when unparseable. */
export function parseHex(value: string, fallback: [number, number, number]): [number, number, number] {
  const hex = value.trim().replace(/^#/, '')
  const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex
  if (!/^[0-9a-f]{6}$/i.test(full)) return fallback
  return [parseInt(full.slice(0, 2), 16) / 255, parseInt(full.slice(2, 4), 16) / 255, parseInt(full.slice(4, 6), 16) / 255]
}

/** feColorMatrix values that turn dark ink into `tint` and keep paper white: out = tint + (1 - tint) * luminance. */
export function tintMatrix(tint: [number, number, number]): string {
  const row = (t: number) => `${((1 - t) * 0.2126).toFixed(4)} ${((1 - t) * 0.7152).toFixed(4)} ${((1 - t) * 0.0722).toFixed(4)} 0 ${t.toFixed(4)}`
  return `${row(tint[0])} ${row(tint[1])} ${row(tint[2])} 0 0 0 1 0`
}
