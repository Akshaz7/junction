import type { SceneEvent } from '../viewer3d/liveHighlight'

/** Covers the synchronous commit of 2D and the mounted model's layout effect. */
export function applyLiveSceneEvent(event: SceneEvent, apply: () => void) {
  if (event.type !== 'scene.edit' || !event.edit_id) { apply(); return }
  const key = `scene-edit:${event.edit_id}`
  const detail = { doc_id: event.doc_id, chat_id: event.chat_id, op: event.op, item_ids: event.item_ids }
  if (!performance.getEntriesByName(`${key}:received`).length) performance.mark(`${key}:received`, { detail })
  apply()
  performance.mark(`${key}:applied`, { detail })
  performance.measure(`${key}:receive-to-applied`, `${key}:received`, `${key}:applied`)
}
