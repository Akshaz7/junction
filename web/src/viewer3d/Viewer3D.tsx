import { useCallback, useEffect, useId, useRef, useState, type PointerEvent } from 'react';
import { documentSceneUrl, SceneLoadError, type SceneManifest } from './scene';
import { buildItemDetails, type IFCElement } from './identify';
import { ItemDetailsCard } from './ItemDetailsCard';
import { createViewer, type Viewer } from './viewer';
import type { HighlightOptions } from './highlight';
import type { RiseState } from './rise';
import { bindLiveHighlight } from './liveViewerHighlight';
import { cutawayStoreys, isRoof, type CutawayState } from './cutaway';
import './viewer3d.css';

interface ViewerOptions {
  onPick?: (item_id: string) => void;
  /** Defaults to a cutaway at the ground storey. Null explicitly shows all storeys. */
  storey?: string | null;
  highlightItemIds?: readonly string[];
  highlightOptions?: HighlightOptions;
  /** Imperative highlight/clearHighlight API, called once the scene is ready. */
  onReady?: (viewer: Viewer) => void;
  visualise?: boolean;
  onRiseStateChange?: (state: RiseState) => void;
  onError?: (message: string) => void;
}

/** Provide a document ID for the API, or an offline scene.json URL. */
export type Viewer3DProps = ViewerOptions & (
  { doc_id: string; sceneUrl?: never } | { sceneUrl: string; doc_id?: never }
);

export function Viewer3D({ sceneUrl: sourceUrl, doc_id, onPick, storey, highlightItemIds, highlightOptions, onReady, visualise = false, onRiseStateChange, onError }: Viewer3DProps) {
  const sceneUrl = doc_id !== undefined ? documentSceneUrl(doc_id) : sourceUrl!;
  // Answer objects may be recreated on parent renders. Only new evidence should
  // replace a live selection; equivalent arrays/maps must leave it in place.
  const highlightRequest = highlightItemIds === undefined ? undefined
    : JSON.stringify([highlightItemIds, highlightOptions ?? {}]);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const onReadyRef = useRef(onReady);
  const riseStateRef = useRef(onRiseStateChange);
  const onErrorRef = useRef(onError);
  const pointerStart = useRef<{ id: number; x: number; y: number } | null>(null);
  const [cutaway, setCutaway] = useState<CutawayState>({ activeStorey: null, showRoof: false, hiddenCount: 0 });
  const [hasRoof, setHasRoof] = useState(false);
  const [storeys, setStoreys] = useState<string[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [manifest, setManifest] = useState<SceneManifest | null>(null);
  const [elements, setElements] = useState<Map<string, IFCElement>>(new Map());
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const selectId = useId();
  const helpId = useId();
  const closeDetails = useCallback(() => setPicked(null), []);
  const details = manifest && picked ? buildItemDetails(manifest, picked, elements.get(picked)) : null;

  useEffect(() => { onReadyRef.current = onReady; }, [onReady]);
  useEffect(() => { riseStateRef.current = onRiseStateChange; }, [onRiseStateChange]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  useEffect(() => {
    if (storey !== undefined) viewerRef.current?.setStorey(storey);
  }, [storey]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let active = true;
    let viewer: Viewer | null = null;
    let live: ReturnType<typeof bindLiveHighlight> | undefined;
    let unsubscribeCutaway: (() => void) | undefined;
    setState('loading');
    setError('');
    setStoreys([]);
    setPicked(null);
    setManifest(null);
    setElements(new Map());
    setHasRoof(false);
    pointerStart.current = null;

    function fail(reason: unknown) {
      if (!active) return;
      const message = reason instanceof SceneLoadError && reason.status === 404
        ? '3D model not available for this document'
        : reason instanceof Error ? reason.message : 'Could not load the 3D scene.';
      setError(message);
      setState('error');
      onErrorRef.current?.(message);
    }

    try {
      viewer = createViewer(canvas);
      viewerRef.current = viewer;
      unsubscribeCutaway = viewer.onCutawayChange(setCutaway);
      live = bindLiveHighlight(viewer, doc_id);
      void viewer.loadScene(sceneUrl).then((scene) => {
        if (!active) return;
        if (storey !== undefined) viewer!.setStorey(storey);
        live?.sceneReady();
        setCutaway(viewer!.getCutawayState());
        setStoreys(cutawayStoreys(scene.manifest).map((entry) => entry.name));
        setHasRoof(Object.entries(scene.manifest.items).some(([id, item]) => isRoof(item.kind, scene.elements?.get(id))));
        setElements(scene.elements ?? new Map());
        setManifest(scene.manifest);
        setState('ready');
        onReadyRef.current?.(viewer!);
      }).catch(fail);
    } catch (reason) {
      fail(reason);
    }

    return () => {
      active = false;
      unsubscribeCutaway?.();
      live?.dispose();
      viewer?.dispose();
      if (viewerRef.current === viewer) viewerRef.current = null;
    };
  }, [sceneUrl]);

  useEffect(() => {
    if (state !== 'ready' || highlightRequest === undefined) return;
    const [ids, options] = JSON.parse(highlightRequest) as [string[], HighlightOptions];
    viewerRef.current?.highlight(ids, options);
  }, [state, highlightRequest, sceneUrl]);

  useEffect(() => {
    if (state === 'ready' && visualise) {
      viewerRef.current?.visualise((next) => riseStateRef.current?.(next));
    }
  }, [state, visualise, sceneUrl]);

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

  const storeyIndex = storeys.indexOf(cutaway.activeStorey ?? '');
  function selectStorey(name: string | null) {
    viewerRef.current?.setStorey(name);
    setPicked(null);
  }

  return <section className="viewer3d" aria-label="3D viewer" data-state={state}
    data-active-storey={cutaway.activeStorey ?? ''} data-show-roof={cutaway.showRoof} data-hidden-count={cutaway.hiddenCount}>
    <div className="viewer3d-toolbar">
      <label htmlFor={selectId}>Storey</label>
      <button type="button" aria-label="Previous storey" disabled={state !== 'ready' || storeyIndex <= 0}
        onClick={() => selectStorey(storeys[storeyIndex - 1])}>−</button>
      <select id={selectId} value={cutaway.activeStorey ?? ''} disabled={state !== 'ready'}
        onChange={(event) => selectStorey(event.target.value || null)}>
        <option value="">All storeys</option>
        {storeys.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
      <button type="button" aria-label="Next storey" disabled={state !== 'ready' || storeyIndex >= storeys.length - 1}
        onClick={() => selectStorey(storeys[storeyIndex + 1])}>+</button>
      {hasRoof && <label className="viewer3d-roof-toggle">
        <input type="checkbox" checked={cutaway.showRoof}
          onChange={(event) => viewerRef.current?.setShowRoof(event.target.checked)} /> Show roof
      </label>}
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
      {state === 'ready' && details && <ItemDetailsCard key={details.item_id} details={details}
        loading={false} onClose={closeDetails}
        onHighlight={() => viewerRef.current?.highlight([details.item_id])} />}
    </div>
    <div className="viewer3d-footer">
      <p id={helpId}>Drag to orbit · Scroll to zoom · Click an item to identify it</p>
      <output aria-label="Picked item" aria-live="polite">{picked ?? 'No item selected'}</output>
    </div>
  </section>;
}

export default Viewer3D;
