import { useEffect, useId, useRef, useState, type PointerEvent } from 'react';
import { storeyName } from './scene';
import { createViewer, type Viewer } from './viewer';
import type { HighlightOptions } from './highlight';
import './viewer3d.css';

export interface Viewer3DProps {
  /** A CONTRACT 5.5 scene.json URL, including /api/docs/{doc_id}/scene. */
  sceneUrl: string;
  onPick?: (item_id: string) => void;
  /** Null shows all storeys. Changes to this prop update the dropdown and model. */
  storey?: string | null;
  highlightItemIds?: readonly string[];
  highlightOptions?: HighlightOptions;
  /** Imperative highlight/clearHighlight API, called once the scene is ready. */
  onReady?: (viewer: Viewer) => void;
}

export function Viewer3D({ sceneUrl, onPick, storey = null, highlightItemIds, highlightOptions, onReady }: Viewer3DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const onReadyRef = useRef(onReady);
  const pointerStart = useRef<{ id: number; x: number; y: number } | null>(null);
  const [selectedStorey, setSelectedStorey] = useState<string | null>(storey);
  const [storeys, setStoreys] = useState<string[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const selectId = useId();
  const helpId = useId();

  useEffect(() => { onReadyRef.current = onReady; }, [onReady]);

  useEffect(() => {
    setSelectedStorey(storey);
  }, [storey]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let active = true;
    let viewer: Viewer | null = null;
    setState('loading');
    setError('');
    setStoreys([]);
    setPicked(null);
    pointerStart.current = null;

    function fail(reason: unknown) {
      if (!active) return;
      setError(reason instanceof Error ? reason.message : 'Could not load the 3D scene.');
      setState('error');
    }

    try {
      viewer = createViewer(canvas);
      viewerRef.current = viewer;
      void viewer.loadScene(sceneUrl).then((scene) => {
        if (!active) return;
        const names = [
          ...scene.manifest.storeys.map(storeyName),
          ...Object.values(scene.manifest.items).map((item) => storeyName(item.storey)),
        ].filter((name): name is string => name !== null);
        setStoreys([...new Set(names)]);
        setState('ready');
        onReadyRef.current?.(viewer!);
      }).catch(fail);
    } catch (reason) {
      fail(reason);
    }

    return () => {
      active = false;
      viewer?.dispose();
      if (viewerRef.current === viewer) viewerRef.current = null;
    };
  }, [sceneUrl]);

  useEffect(() => {
    viewerRef.current?.setStorey(selectedStorey);
    setPicked(null);
  }, [selectedStorey, sceneUrl]);

  useEffect(() => {
    if (state !== 'ready' || highlightItemIds === undefined) return;
    viewerRef.current?.highlight(highlightItemIds, highlightOptions);
  }, [state, highlightItemIds, highlightOptions, sceneUrl]);

  function pick(event: PointerEvent<HTMLCanvasElement>) {
    const start = pointerStart.current;
    pointerStart.current = null;
    // An orbit drag must not select the surface under the release point.
    if (!start || start.id !== event.pointerId
      || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
    const itemId = viewerRef.current?.pick(event.clientX, event.clientY) ?? null;
    setPicked(itemId);
    if (itemId !== null) onPick?.(itemId);
  }

  return <section className="viewer3d" aria-label="3D viewer" data-state={state}>
    <div className="viewer3d-toolbar">
      <label htmlFor={selectId}>Storey</label>
      <select id={selectId} value={selectedStorey ?? ''} disabled={state !== 'ready'}
        onChange={(event) => setSelectedStorey(event.target.value || null)}>
        <option value="">All storeys</option>
        {selectedStorey !== null && !storeys.includes(selectedStorey)
          && <option value={selectedStorey}>{selectedStorey}</option>}
        {storeys.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </div>
    <div className="viewer3d-stage" aria-busy={state === 'loading'}>
      <canvas ref={canvasRef} aria-label="3D building model" aria-describedby={helpId}
        onPointerDown={(event) => {
          pointerStart.current = event.isPrimary && event.button === 0
            ? { id: event.pointerId, x: event.clientX, y: event.clientY } : null;
        }}
        onPointerUp={pick} onPointerCancel={() => { pointerStart.current = null; }} />
      {state === 'loading' && <p className="viewer3d-message" role="status">Loading 3D scene…</p>}
      {state === 'error' && <p className="viewer3d-message" role="alert">{error}</p>}
    </div>
    <div className="viewer3d-footer">
      <p id={helpId}>Drag to orbit · Scroll to zoom · Click an item to identify it</p>
      <output aria-label="Picked item" aria-live="polite">{picked ?? 'No item selected'}</output>
    </div>
  </section>;
}

export default Viewer3D;
