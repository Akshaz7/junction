import type { Answer } from './types'

export interface TableSelection { doc_id: string; item_ids: string[]; chat_id?: string }
type NativeHost = { webkit?: { messageHandlers?: { ar?: { postMessage: (selection: TableSelection) => void } } } }
declare global { interface Window extends NativeHost {} }

export function arHandler(host: NativeHost) {
  const handler = host.webkit?.messageHandlers?.ar
  return typeof handler?.postMessage === 'function' ? handler : null
}

export function answerTableSelection(answer: Answer): TableSelection | null {
  const doc_id = answer.evidence.scene.doc_id || answer.doc_ids[0]
  if (!doc_id || answer.answer.abstained) return null
  const item_ids = answer.evidence.scene.highlight_item_ids.length
    ? answer.evidence.scene.highlight_item_ids
    : answer.evidence.boxes.length ? answer.evidence.boxes.map((box) => box.item_id)
      : answer.citations.filter((citation) => citation.doc_id === doc_id).flatMap((citation) => citation.item_ids)
  return item_ids.length ? { doc_id, item_ids: [...item_ids] } : null
}

export function showOnTable(selection: TableSelection, host: NativeHost = window as NativeHost) {
  arHandler(host)?.postMessage({ doc_id: selection.doc_id, item_ids: [...selection.item_ids],
    ...(selection.chat_id ? { chat_id: selection.chat_id } : {}) })
}
