import { describe, expect, it } from 'vitest'
import { PNG } from 'pngjs'
import { compareFrames } from '../../e2e/fidelity-diff'

function png(changes: [number, number][] = []) {
  const image = new PNG({ width: 64, height: 64 })
  image.data.fill(255)
  for (const [x, y] of changes) { const index = (y * 64 + x) * 4; image.data[index] = 0; image.data[index + 1] = 0; image.data[index + 2] = 0 }
  return PNG.sync.write(image)
}

describe('fidelity measurement', () => {
  it('counts all unmasked pixels, unions overlapping masks and reports tolerated specks', () => {
    const result = compareFrames(png([[8, 8], [40, 40]]), png(), [
      { x: 0, y: 0, width: 8, height: 8, reason: 'Generated drawing' },
      { x: 0, y: 0, width: 8, height: 8, reason: 'Overlapping generated drawing' },
    ])
    expect(result.masked_pixels).toBe(256)
    expect(result.mismatch_pixels).toBe(1)
    expect(result.mismatch_percent).toBe(100 / (4096 - 256))
    expect(result.unmasked_diff_regions).toEqual([{ x: 16, y: 16, width: 16, height: 16, mismatch_pixels: 1, canvas_percent: 100 / 4096 }])
    expect(result.unexplained_regions).toEqual([])
    expect(result.status).toBe('pass')
  })
  it('fails a connected region above 0.5% of the canvas even when the total is below 1.5%', () => {
    const changes: [number, number][] = Array.from({ length: 36 }, (_, i) => [4 + i % 6, 4 + Math.floor(i / 6)])
    const result = compareFrames(png(changes), png(), [])
    expect(result.mismatch_percent).toBeLessThan(1.5)
    expect(result.unexplained_regions).toHaveLength(1)
    expect(result.unexplained_regions[0].canvas_percent).toBeGreaterThan(.5)
    expect(result.status).toBe('fail')
  })
  it('also fails excessive total mismatch made of individually permitted regions', () => {
    const reference = new PNG({ width: 128, height: 128 }); reference.data.fill(255)
    const actual = new PNG({ width: 128, height: 128 }); actual.data.fill(255)
    for (const x of [2, 34, 66, 98]) for (const y of [2, 34, 66, 98]) {
      for (let dx = 0; dx < 5; dx++) for (let dy = 0; dy < 5; dy++) {
        const index = ((y + dy) * 128 + x + dx) * 4
        actual.data[index] = 0; actual.data[index + 1] = 0; actual.data[index + 2] = 0
      }
    }
    const scattered = compareFrames(PNG.sync.write(actual), PNG.sync.write(reference), [], 1)
    expect(scattered.unmasked_diff_regions).toHaveLength(16)
    expect(scattered.unexplained_regions).toEqual([])
    expect(scattered.mismatch_percent).toBeGreaterThan(1.5)
    expect(scattered.status).toBe('fail')
  })
  it('passes equal canvases and rejects empty comparisons and incompatible resolutions', () => {
    const equal = compareFrames(png(), png(), [])
    expect(equal.status).toBe('pass')
    expect(equal.mismatch_percent).toBe(0)
    expect(equal.unexplained_regions).toEqual([])
    expect(PNG.sync.read(equal.diff).data.every((value) => value === 0)).toBe(true)
    expect(() => compareFrames(png(), png(), [{ x: 0, y: 0, width: 32, height: 32, reason: 'Invalid full mask' }])).toThrow('complete canvas')
    expect(() => compareFrames(png(), PNG.sync.write(new PNG({ width: 8, height: 8 })), [])).toThrow('Canvas mismatch')
  })
})
