import { describe, expect, it } from 'vitest'
import { fitPage, fitPhonePage, focusBox, pageToScreen, screenToPage, zoomAt } from './page-transform'

describe('page pixels to drawing viewport coordinates', () => {
  it('applies scale before pan and reverses it at fractional zoom', () => {
    const view = { scale: 0.375, x: -137, y: 42 }
    expect(pageToScreen({ x: 800, y: 400 }, view)).toEqual({ x: 163, y: 192 })
    expect(screenToPage({ x: 163, y: 192 }, view)).toEqual({ x: 800, y: 400 })
  })

  it('fits portrait and landscape pages with space on every side', () => {
    for (const image of [{ width: 1200, height: 900 }, { width: 900, height: 1600 }]) {
      const viewport = { width: 500, height: 600 }
      const view = fitPage(image, viewport)
      const top = pageToScreen({ x: 0, y: 0 }, view)
      const bottom = pageToScreen({ x: image.width, y: image.height }, view)
      expect(top.x).toBeGreaterThanOrEqual(24)
      expect(top.y).toBeGreaterThanOrEqual(24)
      expect(bottom.x).toBeLessThanOrEqual(476)
      expect(bottom.y).toBeLessThanOrEqual(576)
    }
  })

  it('keeps a wheel or pinch anchor on the same page point after zooming', () => {
    const view = { scale: 0.5, x: -120, y: 30 }
    const anchor = { x: 220, y: 170 }
    const point = screenToPage(anchor, view)
    expect(pageToScreen(point, zoomAt(view, anchor, 2))).toEqual(anchor)
  })

  it('opens phone pages at the top, fits their width and never enlarges small images', () => {
    const viewport = { width: 390, height: 699 }
    for (const image of [{ width: 2384, height: 1684 }, { width: 440, height: 320 }, { width: 160, height: 90 }, { width: 1200, height: 4000 }]) {
      const view = fitPhonePage(image, viewport)
      expect(view.scale).toBeLessThanOrEqual(1)
      expect(pageToScreen({ x: 0, y: 0 }, view).y).toBe(12)
      expect(pageToScreen({ x: image.width / 2, y: 0 }, view).x).toBeCloseTo(viewport.width / 2)
      expect(image.width * view.scale).toBeCloseTo(Math.min(image.width, 366))
    }
  })

  it('centres edge boxes and reduces zoom if a box would be clipped', () => {
    const viewport = { width: 400, height: 300 }
    const box: [number, number, number, number] = [900, 700, 1600, 1200]
    const view = focusBox(box, viewport, 2)
    expect(pageToScreen({ x: 1250, y: 950 }, view)).toEqual({ x: 200, y: 150 })
    const start = pageToScreen({ x: box[0], y: box[1] }, view)
    const end = pageToScreen({ x: box[2], y: box[3] }, view)
    expect(start.x).toBeGreaterThanOrEqual(32)
    expect(start.y).toBeGreaterThanOrEqual(32)
    expect(end.x).toBeLessThanOrEqual(368)
    expect(end.y).toBeLessThanOrEqual(268)
  })
})
