import { useCallback, useContext, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Viewer3D } from '../viewer3d/Viewer3D'
import { answerToVisualise, type VisualiseAnswer } from '../viewer3d/visualise'
import type { RisePhase } from '../viewer3d/rise'
import type { Viewer } from '../viewer3d/viewer'
import { DrawingEditsContext } from '../lib/scene-edit-context'
import { drawingSnapshot, syncSceneSnapshot } from '../lib/scene-snapshot'

/** A nonmodal model pane in the drawing column leaves chat and 2D controls usable. */
export function DrawingModel({ answer, docId, chatId }: { answer?: VisualiseAnswer; docId: string; chatId?: string | null }) {
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<RisePhase | 'loading' | 'error'>('loading')
  const titleId = useId()
  const trigger = useRef<HTMLButtonElement>(null)
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
    if (open && snapshot && viewer.current) syncSceneSnapshot(viewer.current, snapshot)
  }, [open, snapshot])
  const evidence = useMemo<ReturnType<typeof answerToVisualise>>(() => answer ? answerToVisualise(answer)
    : { docId, highlight: [], labels: {}, cameraTargetItemId: undefined }, [answer, docId])
  const highlightOptions = useMemo(() => ({ labels: evidence.labels, cameraTargetItemId: evidence.cameraTargetItemId }), [evidence])
  function close() { viewer.current = null; setOpen(false); trigger.current?.focus() }

  return <div className={`drawing-model ${open ? 'is-open' : ''}`}>
    <button ref={trigger} type="button" className="viewer3d-visualise-button" aria-haspopup="dialog" aria-expanded={open}
      onClick={() => { if (!open) { setPhase('loading'); setOpen(true) } }}>Visualise it</button>
    {open && <dialog open className="viewer3d-visualise-panel viewer3d-linked-panel drawing-model-panel" aria-labelledby={titleId}
      data-rise-state={phase} onKeyDown={(event) => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
      }}>
      <header className="viewer3d-visualise-heading"><div><h2 id={titleId}>Visualise it</h2><p>{docId}</p></div>
        <button type="button" aria-label="Close 3D view" onClick={close}>Close</button>
      </header>
      <Viewer3D doc_id={evidence.docId} chat_id={chatId ?? undefined} highlightItemIds={drawing ? undefined : evidence.highlight} highlightOptions={highlightOptions}
        commands={drawing ? undefined : evidence.commands} onReady={ready} visualise onRiseStateChange={(state) => setPhase(state.phase)} onError={() => setPhase('error')} />
      <p className="viewer3d-rise-status" role="status" aria-live="polite">{phase === 'loading' ? 'Loading 3D scene…' : phase === 'flat' ? 'Plan view' : phase === 'rising' ? 'Raising the model…' : phase === 'done' ? '3D view ready' : ''}</p>
    </dialog>}
  </div>
}
