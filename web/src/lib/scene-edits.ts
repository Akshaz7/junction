import { applyCommand, applyState, emptyCommandState, type CommandState } from '../viewer3d/commands'
import type { SceneEvent } from '../viewer3d/liveHighlight'
import type { Answer } from './types'

export interface DrawingEdits {
  state: CommandState
  tags: Record<string, string>
}
export interface ChatEdits {
  docs: Record<string, DrawingEdits>
  seen: ReadonlySet<string>
}
export const emptyChatEdits = (): ChatEdits => ({ docs: {}, seen: new Set() })

export function reduceSceneEvent(previous: ChatEdits, event: SceneEvent): ChatEdits {
  const drawing = previous.docs[event.doc_id]
  if (event.type === 'scene.edit' && event.edit_id && previous.seen.has(event.edit_id)) {
    // The server strips hide/restore labels on the socket. Its SSE answer can
    // enrich the same edit's tags without applying the old command again.
    if (!drawing || !Object.entries(event.labels ?? {}).some(([id, tag]) => drawing.tags[id] !== tag)) return previous
    return { ...previous, docs: { ...previous.docs, [event.doc_id]: { ...drawing, tags: { ...drawing.tags, ...event.labels } } } }
  }
  const state = event.type === 'scene.state' ? applyState(event) : applyCommand(drawing?.state ?? emptyCommandState(), event)
  // Keep stable tags after hide/reset removes the highlight labels.
  const tags = { ...drawing?.tags, ...event.labels }
  const seen = new Set(previous.seen)
  if (event.type === 'scene.edit' && event.edit_id) seen.add(event.edit_id)
  return { docs: { ...previous.docs, [event.doc_id]: { state, tags } }, seen }
}

export function answerSceneEvents(answer: Answer): SceneEvent[] {
  if (answer.answer.abstained) return []
  const doc_id = answer.evidence.scene.doc_id || answer.doc_ids[0]
  if (!doc_id) return []
  return (answer.evidence.scene.commands ?? []).map((command, n) => ({
    ...command, item_ids: [...command.item_ids], labels: command.labels ? { ...command.labels } : undefined,
    type: 'scene.edit', doc_id, edit_id: `${answer.answer_id}-${n}`,
  }))
}

export function itemIsHidden(drawing: DrawingEdits | undefined, id: string): boolean {
  return !!drawing && (drawing.state.hidden.has(id) || (drawing.state.isolated !== null && !drawing.state.isolated.has(id)))
}

export function answerTags(answer: Answer): { id: string; tag: string }[] {
  const tags = new Map<string, string>()
  for (const command of answer.evidence.scene.commands ?? []) {
    for (const id of command.item_ids) tags.set(id, command.labels?.[id] ?? id)
  }
  return [...tags].map(([id, tag]) => ({ id, tag })).sort((a, b) => a.tag.localeCompare(b.tag, 'en', { numeric: true }))
}
