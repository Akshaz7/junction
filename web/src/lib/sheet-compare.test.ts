import { expect, it } from 'vitest'
import {
  boxRect, fitSheet, nudgeSeam, panView, regionView, screenToWorld, seamFromPointer, shortVersion, stepZoom, tintMatrix,
  thumbLayout, contrastMatrix, versionDate, worldToScreen, zoomAt, usableBox, FIT_VIEW, parseHex,
} from './sheet-compare'

const viewport = { w: 499, h: 525 }
const sheet = { w: 6300, h: 4500 }

it('seam follows the pointer and never leaves the canvas', () => {
  expect(seamFromPointer(150, 100, 500)).toBe(10)
  expect(seamFromPointer(-40, 100, 500)).toBe(0)
  expect(seamFromPointer(900, 100, 500)).toBe(100)
  expect(seamFromPointer(100, 100, 0)).toBe(50)
})

it('keyboard moves the seam by 1, shift 10, and jumps to the ends', () => {
  expect(nudgeSeam(50, 'ArrowRight')).toBe(51)
  expect(nudgeSeam(50, 'ArrowLeft')).toBe(49)
  expect(nudgeSeam(50, 'ArrowRight', true)).toBe(60)
  expect(nudgeSeam(3, 'ArrowLeft', true)).toBe(0)
  expect(nudgeSeam(98, 'PageUp')).toBe(100)
  expect(nudgeSeam(40, 'Home')).toBe(0)
  expect(nudgeSeam(40, 'End')).toBe(100)
  expect(nudgeSeam(40, 'a')).toBeNull()
})

it('fits a landscape sheet to 479 px wide in a 499 px canvas, and portrait sheets by height', () => {
  const fit = fitSheet(viewport, sheet)
  expect(fit.w).toBeCloseTo(479, 5)
  expect(fit.h).toBeCloseTo(479 * 4500 / 6300, 5)
  const tall = fitSheet(viewport, { w: 100, h: 400 })
  expect(tall.h).toBeCloseTo(505, 5)
  expect(fitSheet({ w: 0, h: 0 }, sheet)).toEqual({ w: 0, h: 0 })
})

it('places the fitted sheet at left 10 and centred vertically', () => {
  const fit = fitSheet(viewport, sheet)
  const origin = worldToScreen(0, 0, FIT_VIEW, fit, viewport)
  expect(origin.x).toBeCloseTo(10, 5)
  expect(origin.y).toBeCloseTo((525 - fit.h) / 2, 5)
})

it('box placement keeps its sheet position under zoom and pan, and min size is 9 px', () => {
  const fit = fitSheet(viewport, sheet)
  const bbox: [number, number, number, number] = [630, 450, 1260, 900]
  const base = boxRect(bbox, sheet, FIT_VIEW, fit, viewport)
  expect(base.width).toBeCloseTo(0.1 * fit.w, 5)
  const zoomed = { s: 2, cx: 0.5, cy: 0.5 }
  const z = boxRect(bbox, sheet, zoomed, fit, viewport)
  expect(z.width).toBeCloseTo(base.width * 2, 5)
  // The same sheet point projects to the same world point after a round trip.
  const back = screenToWorld(z.left, z.top, zoomed, fit, viewport)
  expect(back.u).toBeCloseTo(0.1, 5)
  expect(back.v).toBeCloseTo(0.1, 5)
  const tiny = boxRect([100, 100, 101, 101], sheet, FIT_VIEW, fit, viewport)
  expect(tiny.width).toBe(9)
  expect(tiny.height).toBe(9)
})

it('panning moves the sheet with the pointer and stays inside the sheet', () => {
  const fit = fitSheet(viewport, sheet)
  const view = { s: 2, cx: 0.5, cy: 0.5 }
  const before = worldToScreen(0.5, 0.5, view, fit, viewport)
  const moved = panView(view, 40, -20, fit)
  const after = worldToScreen(0.5, 0.5, moved, fit, viewport)
  expect(after.x - before.x).toBeCloseTo(40, 5)
  expect(after.y - before.y).toBeCloseTo(-20, 5)
  expect(panView(view, 1e6, 1e6, fit).cx).toBe(0)
})

it('zoom keeps the point under the cursor fixed', () => {
  const fit = fitSheet(viewport, sheet)
  const anchor = { x: 300, y: 200 }
  const before = screenToWorld(anchor.x, anchor.y, FIT_VIEW, fit, viewport)
  const next = zoomAt(FIT_VIEW, 3, anchor, fit, viewport)
  const after = screenToWorld(anchor.x, anchor.y, next, fit, viewport)
  expect(after.u).toBeCloseTo(before.u, 5)
  expect(after.v).toBeCloseTo(before.v, 5)
  expect(zoomAt(FIT_VIEW, 99, anchor, fit, viewport).s).toBe(12)
})

it('zoom steps walk 25..1200 and stop at the ends', () => {
  expect(stepZoom(100, 1)).toBe(150)
  expect(stepZoom(100, -1)).toBe(75)
  expect(stepZoom(130, 1)).toBe(150)
  expect(stepZoom(25, -1)).toBe(25)
  expect(stepZoom(1200, 1)).toBe(1200)
})

it('zoom to a region centres it and fills about 60% of the canvas', () => {
  const fit = fitSheet(viewport, sheet)
  const bbox: [number, number, number, number] = [3150, 2250, 3780, 2700]
  const view = regionView(bbox, sheet, fit, viewport)
  const rect = boxRect(bbox, sheet, view, fit, viewport)
  expect(rect.left + rect.width / 2).toBeCloseTo(viewport.w / 2, 3)
  expect(rect.top + rect.height / 2).toBeCloseTo(viewport.h / 2, 3)
  expect(rect.width).toBeLessThanOrEqual(viewport.w * 0.6 + 0.5)
  expect(rect.height).toBeLessThanOrEqual(viewport.h * 0.6 + 0.5)
  expect(view.s).toBeGreaterThan(1)
  expect(regionView([10, 10, 20, 20], sheet, fit, viewport).s).toBe(5)
  // A whole-sheet region never zooms out.
  expect(regionView([0, 0, 6300, 4500], sheet, fit, viewport).s).toBe(1)
})

it('thumbnail zoom follows min(118/(w*1.5), 68*aspect/(h*1.5), 900) and centres the region', () => {
  const aspect = 6300 / 4500
  const wide = thumbLayout([0, 0, 630, 90], sheet)   // 10% wide, 2% tall: width limited
  expect(wide.zoom).toBeCloseTo(Math.min(118 / (0.1 * 1.5), 68 * aspect / (0.02 * 1.5), 900), 5)
  const tall = thumbLayout([0, 0, 63, 900], sheet)   // 1% wide, 20% tall: height limited
  expect(tall.zoom).toBeCloseTo(68 * aspect / (0.2 * 1.5), 5)
  const tiny = thumbLayout([10, 10, 11, 11], sheet)  // capped at 900
  expect(tiny.zoom).toBe(900)
  const box: [number, number, number, number] = [1260, 900, 1890, 1350]
  const t = thumbLayout(box, sheet)
  // Region centre lands on the frame centre (59, 34).
  expect(t.left + (0.25) * t.width).toBeCloseTo(59, 5)
  expect(t.top + (0.25) * t.height).toBeCloseTo(34, 5)
  expect(t.height).toBeCloseTo(t.width / aspect, 5)
})

it('usableBox rejects missing, inverted and non-finite boxes', () => {
  expect(usableBox([0, 0, 10, 10], sheet)).toBe(true)
  expect(usableBox(null, sheet)).toBe(false)
  expect(usableBox([10, 10, 5, 20], sheet)).toBe(false)
  expect(usableBox([0, 0, NaN, 5], sheet)).toBe(false)
  expect(usableBox([0, 0, 10, 10], { w: 0, h: 0 })).toBe(false)
})

it('short version labels drop the date, which moves to a tooltip', () => {
  expect(shortVersion('Version 5 · 2 Nov 2026')).toBe('Version 5')
  expect(shortVersion('Version 3')).toBe('Version 3')
  expect(shortVersion('')).toBe('Version')
  expect(versionDate('Version 5 · 2 Nov 2026')).toBe('2 Nov 2026')
  expect(versionDate('Version 5')).toBe('')
})

it('tint matrix keeps white paper white and turns black ink into the tint', () => {
  // (also: mid grey linework becomes fully tinted, see below)
  const m = tintMatrix(parseHex('#ca482a', [1, 0, 0])).split(' ').map(Number)
  const apply = (r: number, g: number, b: number) => [0, 1, 2].map((row) => m[row * 5] * r + m[row * 5 + 1] * g + m[row * 5 + 2] * b + m[row * 5 + 4])
  expect(apply(1, 1, 1).every((v) => Math.abs(v - 1) < 1e-3)).toBe(true)
  const ink = apply(0, 0, 0)
  expect(ink[0]).toBeCloseTo(0xca / 255, 3)
  expect(ink[1]).toBeCloseTo(0x48 / 255, 3)
  const c = contrastMatrix().split(' ').map(Number)
  const lum = (v: number) => Math.min(1, Math.max(0, c[0] * v + c[1] * v + c[2] * v + c[4]))
  expect(lum(1)).toBeCloseTo(1, 3)
  expect(lum(0.4)).toBe(0)        // mid-dark linework becomes solid ink
  expect(parseHex('nope', [1, 2, 3])).toEqual([1, 2, 3])
})
