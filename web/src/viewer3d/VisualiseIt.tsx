import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Viewer3D } from './Viewer3D';
import type { Viewer } from './viewer';
import type { RisePhase } from './rise';
import type { SceneCommand } from './commands';
import { answerToVisualise, type VisualiseAnswer } from './visualise';
import './viewer3d.css';

const NO_HIGHLIGHTS: readonly string[] = [];

export interface VisualisePanelProps {
  docId: string;
  highlight?: readonly string[];
  labels?: Record<string, string>;
  commands?: readonly SceneCommand[];
  cameraTargetItemId?: string;
  onClose: () => void;
  onReady?: (viewer: Viewer) => void;
  /** Keep the drawing interactive alongside the model on desktop. */
  linked?: boolean;
}

export function VisualisePanel({ docId, highlight = NO_HIGHLIGHTS, labels, commands, cameraTargetItemId, onClose, onReady, linked = false }: VisualisePanelProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [phase, setPhase] = useState<RisePhase | 'loading' | 'error'>('loading');
  const highlightOptions = useMemo(() => ({ labels, cameraTargetItemId }), [labels, cameraTargetItemId]);

  useEffect(() => {
    const dialog = dialogRef.current!;
    const previousFocus = document.activeElement;
    if (linked) dialog.show();
    else dialog.showModal();
    return () => {
      dialog.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [linked]);

  useEffect(() => { setPhase('loading'); }, [docId]);

  const panel = <dialog ref={dialogRef} className={`viewer3d-visualise-panel${linked ? ' viewer3d-linked-panel' : ''}`} aria-labelledby={titleId}
    data-rise-state={phase} onCancel={(event) => { event.preventDefault(); onClose(); }}
    onKeyDown={(event) => {
      if (event.key === 'Escape' && linked) { event.preventDefault(); event.stopPropagation(); onClose(); }
    }}>
    <header className="viewer3d-visualise-heading">
      <div>
        <h2 id={titleId}>Visualise it</h2>
        <p>{docId}</p>
      </div>
      <button type="button" onClick={onClose} autoFocus aria-label="Close 3D view">Close</button>
    </header>
    <Viewer3D key={docId} doc_id={docId} highlightItemIds={highlight} highlightOptions={highlightOptions}
      commands={commands}
      visualise onRiseStateChange={(state) => setPhase(state.phase)} onError={() => setPhase('error')} onReady={onReady} />
    <p className="viewer3d-rise-status" role="status" aria-live="polite">
      {phase === 'loading' ? 'Loading 3D scene…' : phase === 'flat' ? 'Plan view' : phase === 'rising' ? 'Raising the model…' : phase === 'done' ? '3D view ready' : ''}
    </p>
  </dialog>;
  // The drawing panel clips its contents. A portal keeps both viewports visible.
  return linked ? createPortal(panel, document.body) : panel;
}

export type VisualiseItButtonProps = {
  onReady?: (viewer: Viewer) => void;
} & ({ answer: VisualiseAnswer; docId?: never } | { docId: string; answer?: never });

/** Pass a CONTRACT answer on an answer card, or docId on a document. */
export function VisualiseItButton({ answer, docId, onReady }: VisualiseItButtonProps) {
  const [open, setOpen] = useState(false);
  const [linked, setLinked] = useState(false);
  const evidence = useMemo(() => answer ? answerToVisualise(answer) : {
    docId: docId ?? '', highlight: NO_HIGHLIGHTS, labels: undefined, cameraTargetItemId: undefined,
  }, [answer, docId]);

  return <>
    <button className="viewer3d-visualise-button" type="button" disabled={!evidence.docId}
      aria-haspopup="dialog" onClick={(event) => {
        setLinked(!!event.currentTarget.closest('[aria-label="Drawing viewer"]') && window.matchMedia('(min-width: 1000px)').matches);
        setOpen(true);
      }}>Visualise it</button>
    {open && <VisualisePanel {...evidence} linked={linked} onClose={() => setOpen(false)} onReady={onReady} />}
  </>;
}
