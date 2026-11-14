import type { Bbox } from './types'

export type Point = { x: number; y: number }
export type Size = { width: number; height: number }
export type PageTransform = Point & { scale: number }

export function pageToScreen(point: Point, view: PageTransform): Point {
  return { x: point.x * view.scale + view.x, y: point.y * view.scale + view.y }
}

export function screenToPage(point: Point, view: PageTransform): Point {
  return { x: (point.x - view.x) / view.scale, y: (point.y - view.y) / view.scale }
}

export function fitPage(image: Size, viewport: Size): PageTransform {
  const scale = Math.max(0.001, Math.min(Math.max(1, viewport.width - 48) / image.width, Math.max(1, viewport.height - 48) / image.height))
  return { scale, x: (viewport.width - image.width * scale) / 2, y: (viewport.height - image.height * scale) / 2 }
}

/** Phone documents open at their top edge, fitted to width without upscaling. */
export function fitPhonePage(image: Size, viewport: Size): PageTransform {
  const scale = Math.min(1, Math.max(1, viewport.width - 24) / image.width)
  return { scale, x: (viewport.width - image.width * scale) / 2, y: 12 }
}

/** Keep the page point under the wheel/pinch midpoint fixed while zooming. */
export function zoomAt(view: PageTransform, anchor: Point, scale: number): PageTransform {
  const point = screenToPage(anchor, view)
  return { scale, x: anchor.x - point.x * scale, y: anchor.y - point.y * scale }
}

export function focusBox(box: Bbox, viewport: Size, scale: number): PageTransform {
  const visibleScale = Math.min(scale, Math.max(1, viewport.width - 64) / Math.max(1, box[2] - box[0]), Math.max(1, viewport.height - 64) / Math.max(1, box[3] - box[1]))
  return { scale: visibleScale, x: viewport.width / 2 - (box[0] + box[2]) / 2 * visibleScale, y: viewport.height / 2 - (box[1] + box[3]) / 2 * visibleScale }
}

/**
 * Focus a box without leaving empty canvas: when the whole page already fits (focus scale equals the fitted scale)
 * the centred fit is kept, otherwise the focused view is clamped so the page edges never pull away from the viewport.
 */
export function focusBoxWithin(box: Bbox, viewport: Size, image: Size, fitted: PageTransform): PageTransform {
  const focus = focusBox(box, viewport, fitted.scale)
  if (focus.scale <= fitted.scale * 1.001) return fitted
  const clamp = (offset: number, view: number, page: number) => page <= view ? (view - page) / 2 : Math.min(0, Math.max(view - page, offset))
  return { scale: focus.scale, x: clamp(focus.x, viewport.width, image.width * focus.scale), y: clamp(focus.y, viewport.height, image.height * focus.scale) }
}
