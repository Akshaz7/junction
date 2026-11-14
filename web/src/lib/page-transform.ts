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

/** Keep the page point under the wheel/pinch midpoint fixed while zooming. */
export function zoomAt(view: PageTransform, anchor: Point, scale: number): PageTransform {
  const point = screenToPage(anchor, view)
  return { scale, x: anchor.x - point.x * scale, y: anchor.y - point.y * scale }
}

export function focusBox(box: Bbox, viewport: Size, scale: number): PageTransform {
  const visibleScale = Math.min(scale, Math.max(1, viewport.width - 64) / Math.max(1, box[2] - box[0]), Math.max(1, viewport.height - 64) / Math.max(1, box[3] - box[1]))
  return { scale: visibleScale, x: viewport.width / 2 - (box[0] + box[2]) / 2 * visibleScale, y: viewport.height / 2 - (box[1] + box[3]) / 2 * visibleScale }
}
