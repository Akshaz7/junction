import { useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Viewer3D } from '../viewer3d/Viewer3D'
import { answerToVisualise, type VisualiseAnswer } from '../viewer3d/visualise'
import type { RisePhase } from '../viewer3d/rise'
import type { Viewer } from '../viewer3d/viewer'
import { DrawingEditsContext } from '../lib/scene-edit-context'
import { drawingSnapshot, syncSceneSnapshot } from '../lib/scene-snapshot'

export type ViewerMode = '2d' | '3d'

export function ViewerModeToggle({ mode, onChange }: { mode: ViewerMode; onChange: (mode: ViewerMode) => void }) {
  return <div className="viewer-mode-toggle" role="group" aria-label="Viewer mode">
    <button type="button" aria-pressed={mode === '2d'} onClick={() => onChange('2d')}>2D</button>
    <button type="button" aria-pressed={mode === '3d'} onClick={() => onChange('3d')}>3D</button>
  </div>
}

/** The model fills the same pane as the drawing on desktop and phone. */
export function DrawingModel({ answer, docId, chatId }: { answer?: VisualiseAnswer; docId: string; chatId?: string | null }) {
  const [phase, setPhase] = useState<RisePhase | 'loading' | 'error'>('loading')
  const viewer = useRef<Viewer | null>(null)
  const drawing = useContext(DrawingEditsContext)[docId]
  const snapshot = useMemo(() => drawing ? drawingSnapshot(drawing) : undefined, [drawing])
  const latestSnapshot = useRef(snapshot)
  latestSnapshot.current = snapshot
  const ready = useCallback((next: Viewer) => {
    viewer.current = next
    if (latestSnapshot.current) syncSceneSnapshot(next, latestSnapshot.current)
  }, [])
  useLayoutEffect(() => {
    if (snapshot && viewer.current) syncSceneSnapshot(viewer.current, snapshot)
  }, [snapshot])
  const evidence = useMemo<ReturnType<typeof answerToVisualise>>(() => answer ? answerToVisualise(answer)
    : { docId, highlight: [], labels: {}, cameraTargetItemId: undefined }, [answer, docId])
  const highlightOptions = useMemo(() => ({ labels: evidence.labels, cameraTargetItemId: evidence.cameraTargetItemId }), [evidence])
  return <div className="drawing-model" role="region" aria-label="3D model pane" data-rise-state={phase}>
    <Viewer3D doc_id={evidence.docId} chat_id={chatId ?? undefined} highlightItemIds={evidence.highlight} highlightOptions={highlightOptions}
      commands={drawing ? undefined : evidence.commands} onReady={ready} visualise onRiseStateChange={(state) => setPhase(state.phase)} onError={() => setPhase('error')} />
  </div>
}
