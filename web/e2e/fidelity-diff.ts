import pixelmatch from 'pixelmatch'
import { PNG } from 'pngjs'

export type Rect = { x: number; y: number; width: number; height: number }
export type Mask = Rect & { reason: string }
export const MAX_REGION_CANVAS_PERCENT = .5
export const MAX_UNMASKED_MISMATCH_PERCENT = 1.5
// DECISIONS.md, 2026-11-14 05:44: phone residuals may reach 2% only
// when every diff region remains within MAX_REGION_CANVAS_PERCENT.
export const MAX_PHONE_UNMASKED_MISMATCH_PERCENT = 2

/** Fixed 2x reference canvases. No image rescaling, baseline updates or automatic masks. */
export function compareFrames(actualBytes: Buffer, referenceBytes: Buffer, masks: Mask[], scale = 2, device = 'desktop') {
  const actual = PNG.sync.read(actualBytes), reference = PNG.sync.read(referenceBytes)
  if (actual.width !== reference.width || actual.height !== reference.height) {
    throw new Error(`Canvas mismatch: actual ${actual.width}x${actual.height}; reference ${reference.width}x${reference.height}`)
  }
  const { width, height } = actual
  const covered = new Uint8Array(width * height)
  for (const mask of masks) {
    const left = Math.max(0, Math.floor(mask.x * scale)), top = Math.max(0, Math.floor(mask.y * scale))
    const right = Math.min(width, Math.ceil((mask.x + mask.width) * scale)), bottom = Math.min(height, Math.ceil((mask.y + mask.height) * scale))
    for (let y = top; y < bottom; y++) for (let x = left; x < right; x++) covered[y * width + x] = 1
  }
  let maskedPixels = 0
  for (let p = 0; p < covered.length; p++) if (covered[p]) {
    maskedPixels++
    // Apply identical masks to both images; masked boundaries cannot create diff pixels.
    actual.data.fill(255, p * 4, p * 4 + 4)
    reference.data.fill(255, p * 4, p * 4 + 4)
  }
  const comparedPixels = width * height - maskedPixels
  if (!comparedPixels) throw new Error('Masks cover the complete canvas; there is nothing to compare.')
  const diff = new PNG({ width, height })
  // pngjs may allocate an unsafe buffer. In diffMask mode pixelmatch only writes
  // mismatches, leaving equal pixels untouched. Start with transparent pixels.
  diff.data.fill(0)
  const mismatchPixels = pixelmatch(actual.data, reference.data, diff.data, width, height, {
    threshold: .1, includeAA: false, diffMask: true,
  })
  // Connected occupied 16-CSS-pixel tiles keep the report usable while retaining EVERY diff pixel.
  const tile = 16 * scale, cols = Math.ceil(width / tile), rows = Math.ceil(height / tile)
  const tiles = new Uint32Array(cols * rows)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (!covered[y * width + x] && diff.data[(y * width + x) * 4 + 3]) tiles[Math.floor(y / tile) * cols + Math.floor(x / tile)]++
  }
  const regions: (Rect & { mismatch_pixels: number })[] = []
  for (let start = 0; start < tiles.length; start++) {
    if (!tiles[start]) continue
    const stack = [start]
    let left = cols, top = rows, right = 0, bottom = 0, pixels = 0
    while (stack.length) {
      const index = stack.pop()!
      if (!tiles[index]) continue
      pixels += tiles[index]; tiles[index] = 0
      const x = index % cols, y = Math.floor(index / cols)
      left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y)
      if (x > 0) stack.push(index - 1)
      if (x + 1 < cols) stack.push(index + 1)
      if (y > 0) stack.push(index - cols)
      if (y + 1 < rows) stack.push(index + cols)
    }
    regions.push({ x: left * tile / scale, y: top * tile / scale,
      width: (Math.min(width, (right + 1) * tile) - left * tile) / scale,
      height: (Math.min(height, (bottom + 1) * tile) - top * tile) / scale, mismatch_pixels: pixels })
  }
  if (regions.reduce((sum, region) => sum + region.mismatch_pixels, 0) !== mismatchPixels) {
    throw new Error('Diff pixel count and region pixel count disagree.')
  }
  const mismatchPercent = mismatchPixels / comparedPixels * 100
  const unmaskedDiffRegions = regions.map((region) => ({ ...region, canvas_percent: region.mismatch_pixels / (width * height) * 100 }))
  const unexplainedRegions = unmaskedDiffRegions.filter((region) => region.canvas_percent > MAX_REGION_CANVAS_PERCENT)
  return { mismatch_percent: mismatchPercent, mismatch_pixels: mismatchPixels,
    compared_pixels: comparedPixels, masked_pixels: maskedPixels, unmasked_diff_regions: unmaskedDiffRegions,
    unexplained_regions: unexplainedRegions,
    status: unexplainedRegions.length === 0 && mismatchPercent <= (device === 'phone' ? MAX_PHONE_UNMASKED_MISMATCH_PERCENT : MAX_UNMASKED_MISMATCH_PERCENT) ? 'pass' as const : 'fail' as const, diff: PNG.sync.write(diff) }
}
