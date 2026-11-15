import type { KgNode } from './kg'

const GENERIC = /^(doc|document|file|undefined|unnamed|untitled|null|none)?$/i

/** "-1 fundering" -> "Fundering", "00 begane grond" -> "Begane grond". A bare placeholder becomes "Unnamed level". */
export function levelDisplay(label: string): string {
  const text = (label ?? '').trim()
  if (GENERIC.test(text)) return 'Unnamed level'
  const stripped = text.replace(/^[-+]?\d{1,2}[\s._:-]+(?=\p{L})/u, '')
  return stripped ? stripped.charAt(0).toUpperCase() + stripped.slice(1) : text
}

/** What the viewer reads on a node. Ids and filter values keep the raw label; only the text changes. */
export function displayNodes(nodes: KgNode[], docTitles: ReadonlyMap<string, string>): KgNode[] {
  return nodes.map((node) => {
    if (node.kind === 'level') { const label = levelDisplay(node.label); return label === node.label ? node : { ...node, label } }
    if (node.kind === 'doc') {
      const title = node.doc_ids.map((id) => docTitles.get(id)).find(Boolean)
      return title && title !== node.label && (GENERIC.test(node.label.trim()) || title.length >= node.label.length) ? { ...node, label: title } : node
    }
    return node
  })
}
