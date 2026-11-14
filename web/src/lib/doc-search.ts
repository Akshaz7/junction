interface Searchable { doc_id: string; title: string; source?: string; formats?: string[]; folder?: string; licence?: string; credit?: string }

const tokens = (text: string) => text.toLowerCase().split(/[^a-z0-9äöåüß]+/).filter(Boolean)

/** Rank: exact id/title, then title words, then id words, then word prefixes, then any substring. 0 = no match. */
export function searchScore(doc: Searchable, query: string) {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const title = doc.title.toLowerCase(), id = doc.doc_id.toLowerCase()
  if (id === q || title === q) return 5
  const want = tokens(q)
  const inTitle = tokens(title), inId = tokens(id)
  if (want.length && want.every((word) => inTitle.includes(word))) return 4
  if (want.length && want.every((word) => inTitle.includes(word) || inId.includes(word))) return 3
  if (want.length && want.every((word) => [...inTitle, ...inId].some((token) => token.startsWith(word)))) return 2
  const haystack = `${doc.title} ${doc.doc_id} ${doc.source || ''} ${doc.folder || ''} ${(doc.formats || []).join(' ')} ${doc.licence || ''} ${doc.credit || ''}`.toLowerCase()
  return haystack.includes(q) ? 1 : 0
}

/** Matching documents, best match first; equal scores keep their original order. */
export function searchDocuments<T extends Searchable>(docs: T[], query: string) {
  return docs.map((doc, index) => ({ doc, index, score: searchScore(doc, query) })).filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index).map((row) => row.doc)
}
