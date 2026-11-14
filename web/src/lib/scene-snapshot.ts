import type { CommandTestState, SceneSnapshot } from '../viewer3d/commands'
import type { DrawingEdits } from './scene-edits'

export function drawingSnapshot(drawing: DrawingEdits): SceneSnapshot {
  const { state, tags } = drawing
  return {
    hidden: [...state.hidden], highlighted: [...state.highlighted.keys()],
    labels: Object.fromEntries([...state.highlighted].map(([id, label]) => [id, label === id ? tags[id] ?? label : label])),
    isolated: state.isolated === null ? null : [...state.isolated],
  }
}

/** applyState is silent; replaying applyCommand would publish every old edit again. */
export function syncSceneSnapshot(viewer: {
  getCommandState(): CommandTestState
  applyState(snapshot: SceneSnapshot): void
}, snapshot: SceneSnapshot) {
  const current = viewer.getCommandState()
  const sameIds = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((id) => b.includes(id))
  if (sameIds(current.hidden, snapshot.hidden)
    && sameIds(Object.keys(current.highlighted), snapshot.highlighted)
    && snapshot.highlighted.every((id) => current.highlighted[id] === (snapshot.labels[id] ?? id))
    && (current.isolated === null ? snapshot.isolated == null
      : snapshot.isolated != null && sameIds(current.isolated, snapshot.isolated))) return
  viewer.applyState(snapshot)
}
