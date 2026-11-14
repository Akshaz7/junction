/** The accuracy note the PDF-to-3D pipeline writes as `quality.summary` (scene manifest, copied into the answer's reasoning). */
export interface SceneQuality { summary?: string | null; score?: number | null; error?: unknown }

/** One short plain-words line, or null when there is nothing honest to show. */
export function qualitySummary(quality: SceneQuality | null | undefined): string | null {
  if (quality?.error) return null
  const text = typeof quality?.summary === 'string' ? quality.summary.replace(/\s+/g, ' ').trim() : ''
  return text || null
}
