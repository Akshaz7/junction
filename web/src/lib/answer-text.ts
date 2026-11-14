/** Display helpers for answer text: no internal ids, no raw markdown in quotes, simple tables. */

const ID_PATTERN = /\b([a-z][a-z]+)-(\d{1,6})\b/g
const KIND_WORDS = new Set(['room', 'door', 'window', 'wall', 'toilet', 'sink', 'shower', 'bathtub', 'stair', 'stairs', 'slab', 'column', 'beam', 'roof', 'footing', 'pile', 'space', 'fixture'])

/** Replace internal ids (room-004) by the item's label when known, else "Room 4". */
export function humanizeIds(text: string, labels: Record<string, string> = {}): string {
  return text.replace(ID_PATTERN, (match, kind: string, digits: string) => {
    if (!KIND_WORDS.has(kind)) return match
    const named = labels[match]
    if (named && !/^[a-z]+-\d+$/.test(named)) return named
    return `${kind[0].toUpperCase()}${kind.slice(1)} ${Number(digits)}`
  })
}

/** Quotes come from documents: show them as plain text. */
export function plainQuote(text: string): string {
  return text.replace(/\*\*([\s\S]+?)\*\*/g, '$1').replace(/\*\*/g, '').replace(/__([\s\S]+?)__/g, '$1').replace(/`([^`]+)`/g, '$1').trim()
}

export type TextBlock = { type: 'text'; text: string } | { type: 'table'; header: string[]; rows: string[][] }

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}
const isRule = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)

/** Split markdown into plain text paragraphs and pipe tables. */
export function parseBlocks(markdown: string): TextBlock[] {
  const lines = markdown.split('\n')
  const blocks: TextBlock[] = []
  let text: string[] = []
  const flush = () => { if (text.length) blocks.push({ type: 'text', text: text.join('\n') }); text = [] }
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes('|') && i + 1 < lines.length && isRule(lines[i + 1])) {
      flush()
      const header = cells(lines[i])
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(cells(lines[i])); i++ }
      i--
      blocks.push({ type: 'table', header, rows })
    } else text.push(lines[i])
  }
  flush()
  return blocks
}

/** One short line (no table, no list, no second paragraph) needs no "where it is set out" section. */
export function isOneLine(markdown: string): boolean {
  const body = markdown.trim()
  return body.length <= 140 && !body.includes('\n') && !body.includes('|')
}

export const CITATION_CAP = 8

/** The error shown when a stream ends without an answer. */
export const NO_ANSWER_MESSAGE = 'The answer did not arrive. Your question is kept, so you can try again.'
