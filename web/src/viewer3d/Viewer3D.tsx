import { useCallback, useEffect, useId, useRef, useState, type PointerEvent } from 'react';
import { documentFileUrl, documentSceneUrl, SceneLoadError, storeyName, type SceneManifest } from './scene';
import { buildItemDetails, indexElements, type IFCElement } from './identify';
import { ItemDetailsCard } from './ItemDetailsCard';
import { createViewer, type Viewer } from './viewer';
import type { HighlightOptions } from './highlight';
import type { RiseState } from './rise';
import './viewer3d.css';

interface ViewerOptions {
  onPick?: (item_id: string) => void;
  /** Null shows all storeys. Changes to this prop update the dropdown and model. */
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

export function Viewer3D({ sceneUrl: sourceUrl, doc_id, onPick, storey = null, highlightItemIds, highlightOptions, onReady, visualise = false, onRiseStateChange, onError }: Viewer3DProps) {
  const sceneUrl = doc_id !== undefined ? documentSceneUrl(doc_id) : sourceUrl!;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const onReadyRef = useRef(onReady);
  const riseStateRef = useRef(onRiseStateChange);
  const onErrorRef = useRef(onError);
  const pointerStart = useRef<{ id: number; x: number; y: number } | null>(null);
  const [selectedStorey, setSelectedStorey] = useState<string | null>(storey);
  const [storeys, setStoreys] = useState<string[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [manifest, setManifest] = useState<SceneManifest | null>(null);
  const [elements, setElements] = useState<Map<string, IFCElement>>(new Map());
  const [elementsLoading, setElementsLoading] = useState(false);
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
    setManifest(null);
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
      void viewer.loadScene(sceneUrl).then((scene) => {
        if (!active) return;
        const names = [
          ...scene.manifest.storeys.map(storeyName),
          ...Object.values(scene.manifest.items).map((item) => storeyName(item.storey)),
        ].filter((name): name is string => name !== null);
        setStoreys([...new Set(names)]);
        setManifest(scene.manifest);
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
    const url = documentFileUrl(sceneUrl, 'elements.json');
    const controller = new AbortController();
    let active = true;
    setElements(new Map());
    setElementsLoading(url !== null);
    if (url) {
      void fetch(url, { signal: controller.signal }).then(async (response) => {
        if (!response.ok) throw new Error('Additional IFC properties unavailable');
        const index = indexElements(await response.json());
        if (active) setElements(index);
      }).catch(() => {
        // A missing optional index must not prevent identification from scene.json.
      }).finally(() => { if (active) setElementsLoading(false); });
    }
    return () => { active = false; controller.abort(); };
  }, [sceneUrl]);

  useEffect(() => {
    viewerRef.current?.setStorey(selectedStorey);
    setPicked(null);
  }, [selectedStorey, sceneUrl]);

  useEffect(() => {
    if (state !== 'ready' || highlightItemIds === undefined) return;
    viewerRef.current?.highlight(highlightItemIds, highlightOptions);
  }, [state, highlightItemIds, highlightOptions, sceneUrl]);

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
      {state === 'ready' && details && <ItemDetailsCard key={details.item_id} details={details}
        loading={elementsLoading} onClose={closeDetails} />}
    </div>
    <div className="viewer3d-footer">
      <p id={helpId}>Drag to orbit · Scroll to zoom · Click an item to identify it</p>
      <output aria-label="Picked item" aria-live="polite">{picked ?? 'No item selected'}</output>
    </div>
  </section>;
}

export default Viewer3D;
