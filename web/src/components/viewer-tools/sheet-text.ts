import type { Bbox } from '../../lib/types'

export type SheetText = { text: string; bbox: Bbox | null }
type TextItem = { text?: string; label?: string; bbox_px?: Bbox | null }
type TextData = { text?: string; words?: TextItem[]; items?: TextItem[] }

function entries(data: TextData): SheetText[] {
  return (data.words ?? data.items ?? []).flatMap((item) => {
    const text = item.text ?? item.label
    return text?.trim() ? [{ text, bbox: item.bbox_px ?? null }] : []
  })
}

/** Read existing sheet artifacts. Missing OCR/plan maps are normal, never fabricate text. */
export async function loadSheetText(docId: string, page: number, signal: AbortSignal): Promise<SheetText[]> {
  const root = `/api/docs/${encodeURIComponent(docId)}`
  const results = await Promise.allSettled([
    `${root}/files/text-${page}.json`, `${root}/planmap/${page}`,
  ].map(async (url) => {
    const response = await fetch(url, { signal })
    if (response.status === 404) return []
    if (!response.ok) throw new Error('Sheet text could not be loaded. Close search and try again.')
    return entries(await response.json() as TextData)
  }))
  if (signal.aborted) return []
  const values = results.flatMap((result) => result.status === 'fulfilled' ? result.value : [])
  if (!values.length && results.some((result) => result.status === 'rejected')) throw new Error('Sheet text could not be loaded. Close search and try again.')
  const seen = new Set<string>()
  return values.filter((entry) => {
    const key = JSON.stringify(entry)
    if (seen.has(key)) return false
    seen.add(key); return true
  })
}

export function findSheetText(entries: SheetText[], query: string): SheetText[] {
  const needle = query.trim().toLocaleLowerCase().replace(/\s+/g, ' ')
  if (!needle) return []
  // Words stay in extraction order; adjoining words can form a multi-word hit.
  const hits: SheetText[] = []
  for (let i = 0; i < entries.length; i++) {
    let text = entries[i].text
    const first = text.toLocaleLowerCase().replace(/\s+/g, ' ')
    if (!first.includes(needle) && !first.endsWith(needle.split(' ')[0])) continue
    const boxes = entries[i].bbox ? [entries[i].bbox!] : []
    for (let j = i; j < Math.min(entries.length, i + needle.split(' ').length + 1); j++) {
      if (j > i) { text += ` ${entries[j].text}`; if (entries[j].bbox) boxes.push(entries[j].bbox!) }
      if (text.toLocaleLowerCase().replace(/\s+/g, ' ').includes(needle)) {
        hits.push({ text, bbox: boxes.length ? [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])), Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))] : null })
        break
      }
      if (!needle.includes(' ')) break
    }
  }
  return hits
}
