import type { CommandTestState, SceneSnapshot } from '../viewer3d/commands'
import type { DrawingEdits } from './scene-edits'

export function drawingSnapshot(drawing: DrawingEdits): SceneSnapshot {
  const { state, tags } = drawing
  return {
    hidden: [...state.hidden], highlighted: [...state.highlighted.keys()],
    labels: Object.fromEntries([...state.highlighted].map(([id, label]) => [id, label === id ? tags[id] ?? label : label])),
    isolated: state.isolated === null ? null : [...state.isolated],
    ...(drawing.moved ? { moved: drawing.moved } : {}),
    ...(drawing.materials ? { materials: drawing.materials } : {}),
  }
}

/** Shared-layer moves/materials the viewer does not show yet. */
function sharedDiffers(viewer: { getEditState?(): { moveDelta?: Record<string, readonly number[]>; materials: Record<string, string> } },
  snapshot: SceneSnapshot): boolean {
  const now = viewer.getEditState?.()
  if (!now) return false
  if (snapshot.moved) {
    const have = now.moveDelta ?? {}
    for (const id of new Set([...Object.keys(have), ...Object.keys(snapshot.moved)])) {
      const [a, b] = have[id] ?? [0, 0], [c, d] = snapshot.moved[id] ?? [0, 0]
      if (Math.abs(a - c) + Math.abs(b - d) > 1e-6) return true
    }
  }
  if (snapshot.materials) {
    for (const id of new Set([...Object.keys(now.materials), ...Object.keys(snapshot.materials)])) {
      if ((now.materials[id] ?? null) !== (snapshot.materials[id] ?? null)) return true
    }
  }
  return false
}

/** applyState is silent; replaying applyCommand would publish every old edit again. */
export function syncSceneSnapshot(viewer: {
  getCommandState(): CommandTestState
  applyState(snapshot: SceneSnapshot): void
  getEditState?(): { moveDelta?: Record<string, readonly number[]>; materials: Record<string, string> }
}, snapshot: SceneSnapshot) {
  const current = viewer.getCommandState()
  const sameIds = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((id) => b.includes(id))
  if (sameIds(current.hidden, snapshot.hidden)
    && sameIds(Object.keys(current.highlighted), snapshot.highlighted)
    && snapshot.highlighted.every((id) => current.highlighted[id] === (snapshot.labels[id] ?? id))
    && (current.isolated === null ? snapshot.isolated == null
      : snapshot.isolated != null && sameIds(current.isolated, snapshot.isolated))
    && !sharedDiffers(viewer, snapshot)) return
  viewer.applyState(snapshot)
}
