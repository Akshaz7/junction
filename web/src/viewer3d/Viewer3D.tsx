import { useCallback, useEffect, useId, useRef, useState, type PointerEvent } from 'react';
import { documentSceneUrl, SceneLoadError, type SceneManifest } from './scene';
import { buildItemDetails, type IFCElement } from './identify';
import { ItemDetailsCard } from './ItemDetailsCard';
import { createViewer, type Viewer } from './viewer';
import type { HighlightOptions, HighlightState } from './highlight';
import type { BuildState, RiseState } from './rise';
import { KindLegend } from './KindLegend';
import { BuildSlider } from './BuildSlider';
import { bindLiveCommands, bindLiveHighlight } from './liveViewerHighlight';
import { createLiveHighlightClient } from './liveHighlight';
import { clearViewerHighlights, itemsOfPickedKind } from './selection';
import type { CommandTestState, SceneCommand } from './commands';
import { cutawayStoreys, isRoof, serviceLayerLabel, type CutawayState, type ModelLayer } from './cutaway';
import { setHover, setSelected, useLinkedItem } from './link';
import type { LoadProgress } from './loadGLTF';
import type { WalkState } from './walk';
import { WalkJoystick } from './WalkJoystick';
import { EditPanel, useEditAdvisor, type SaveVersionControl } from './EditPanel';
import { editSnapshot, hasEdits as snapshotHasEdits, saveDesignVersion, savedMessage } from '../lib/design-versions';
import type { EditState, ItemEdit } from './edits';
import { RevisedPlanDialog } from './RevisedPlanDialog';
import { FindingsPanel } from './FindingsPanel';
import { ESTIMATE_NOTE, NO_SCALE_NOTE, roomTypeLabel, scaleTrust } from './blueprint';
import { itemKindKey, pipeSizeLabel } from '../lib/kind-colors';
import type { FindingPinState } from './findings';
import { qualitySummary } from '../lib/scene-quality';
import { wallAskHref } from '../lib/wall-details';
import './viewer3d.css';
import { Measure3DOverlay, measure3DStatus, useMeasure3D } from './Measure3D';
import { Layers3D } from './Layers3D';
import { Button } from '../components/ui';
import { Ruler } from 'lucide-react';
import '../components/viewer-tools/plan-inspect.css';
import '../components/viewer-tools/plan-layers.css';
import { PlanHoverTip } from '../components/viewer-tools/plan-hover-tip';
import { planItemSummary, type PlanSummaryItem } from '../lib/plan-item-summary';
import { workspaceApi } from '../lib/api';

interface ViewerOptions {
  chat_id?: string;
  onPick?: (item_id: string) => void;
  /** Defaults to a cutaway at the ground storey. Null explicitly shows all storeys. */
  storey?: string | null;
  highlightItemIds?: readonly string[];
  highlightOptions?: HighlightOptions;
  /** CONTRACT 5.11: ordered answer.evidence.scene.commands. */
  commands?: readonly SceneCommand[];
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

/** Opt in with ?viewer3dTest=1. Picks use the same handler as a real canvas click. */
export interface Viewer3DTestHandle {
  state(): HighlightState;
  commandState(): CommandTestState;
  walk(): WalkState;
  findings(): FindingPinState[];
  pick(item_id: string): boolean;
  /** Camera position and orbit target, to prove a new answer keeps the view. */
  camera(): { position: number[]; target: number[] };
  /** Vertical scale of an item's node (0 = still to be built), to prove highlights show during the build-up. */
  scaleY(item_id: string): number | null;
  /** Whether the item's node is drawn (a removed but highlighted item is a visible ghost). */
  drawn(item_id: string): boolean;
  /** Storey the selector shows and the build-up step label, to prove they agree. */
  storeyAndStep(): { storey: string | null; step: string };
}
export type LinkedViewerCanvas = HTMLCanvasElement & { __viewer3d?: Viewer3DTestHandle };

export function Viewer3D({ sceneUrl: sourceUrl, doc_id, chat_id, onPick, storey, highlightItemIds, highlightOptions, commands, onReady, visualise = false, onRiseStateChange, onError }: Viewer3DProps) {
  const sceneUrl = doc_id !== undefined ? documentSceneUrl(doc_id) : sourceUrl!;
  // Answer objects may be recreated on parent renders. Only new evidence should
  // replace a live selection; equivalent arrays/maps must leave it in place.
  const highlightRequest = highlightItemIds === undefined ? undefined
    : JSON.stringify([highlightItemIds, highlightOptions ?? {}]);
  const commandRequest = commands === undefined ? undefined : JSON.stringify(commands);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [stage, setStage] = useState<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const onReadyRef = useRef(onReady);
  const riseStateRef = useRef(onRiseStateChange);
  const onErrorRef = useRef(onError);
  const onPickRef = useRef(onPick);
  const linked = useLinkedItem();
  const [highlightState, setHighlightState] = useState<HighlightState>({ highlighted: [], dimmed: 0, labels: {} });
  const [answerKinds, setAnswerKinds] = useState<(string | null)[]>([]);
  const [build, setBuild] = useState<BuildState | null>(null);
  const pointerStart = useRef<{ id: number; x: number; y: number } | null>(null);
  const [cutaway, setCutaway] = useState<CutawayState>({ activeStorey: null, showRoof: false, hiddenCount: 0 });
  const [hasRoof, setHasRoof] = useState(false);
  const [serviceLabel, setServiceLabel] = useState<string | null>(null);
  const [layer, setLayer] = useState<ModelLayer>('all');
  const [walking, setWalking] = useState(false);
  const [walkMessage, setWalkMessage] = useState('');
  const [storeys, setStoreys] = useState<string[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const measure3d = useMeasure3D();
  const [manifest, setManifest] = useState<SceneManifest | null>(null);
  // Hover summary (same one-liner as the 2D tooltip), from the drawing's plan map: same item ids as the scene.
  const [planSummaries, setPlanSummaries] = useState<{ items: Map<string, PlanSummaryItem>; mPerPx: number | null }>({ items: new Map(), mPerPx: null });
  const [hoverTip, setHoverTip] = useState<{ text: string; x: number; y: number } | null>(null);
  const summaryDoc = doc_id ?? manifest?.doc_id ?? null;
  useEffect(() => {
    setPlanSummaries({ items: new Map(), mPerPx: null }); setHoverTip(null);
    if (!summaryDoc) return;
    const controller = new AbortController();
    workspaceApi.getPlanMap(summaryDoc, 1, controller.signal).then((pm) => {
      if (controller.signal.aborted) return;
      const items = new Map<string, PlanSummaryItem>();
      for (const item of pm.items ?? []) if (item.bbox_px) items.set(item.item_id, { id: item.item_id, kind: item.kind ?? 'other', label: item.label ?? null, props: item.props ?? null, bbox: item.bbox_px });
      setPlanSummaries({ items, mPerPx: typeof pm.scale?.m_per_px === 'number' ? pm.scale.m_per_px : null });
    }).catch(() => {});
    return () => controller.abort();
  }, [summaryDoc]);
  useEffect(() => { measure3d.stop(); }, [sceneUrl]); // eslint-disable-line react-hooks/exhaustive-deps
  const [editing, setEditing] = useState(false);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const hiddenNow = hiddenIds.length;
  const chatRef = useRef(chat_id);
  chatRef.current = chat_id;
  const [revisedOpen, setRevisedOpen] = useState(false);
  const [moveItem, setMoveItem] = useState<string | null>(null);
  const dragPointer = useRef<number | null>(null);
  const [edits, setEdits] = useState<EditState>({ undoCount: 0, moved: {}, materials: {} });
  const advice = useEditAdvisor(manifest?.doc_id, chat_id);
  const [saved, setSaved] = useState<{ busy: boolean; message?: string; href?: string; parent: number; doc?: string }>({ busy: false, parent: 0 });
  const [elements, setElements] = useState<Map<string, IFCElement>>(new Map());
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailFetched, setDetailFetched] = useState<Set<string>>(new Set());
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const [progress, setProgress] = useState<LoadProgress>({ phase: 'manifest' });
  const selectId = useId();
  const helpId = useId();
  const closeDetails = useCallback(() => setPicked(null), []);
  const details = manifest && picked ? buildItemDetails(manifest, picked, elements.get(picked)) : null;
  if (details && manifest && picked && manifest.items[picked]?.kind === 'wall') {
    details.askHref = wallAskHref(manifest.doc_id, manifest.items[picked].tag || picked);
  }

  useEffect(() => {
    if (!picked || !manifest || detailFetched.has(`${manifest.doc_id}/${picked}`) || !/^\/api\/docs\//.test(sceneUrl)) return;
    const controller = new AbortController();
    setDetailsLoading(true);
    void fetch(`/api/docs/${encodeURIComponent(manifest.doc_id)}/items/${encodeURIComponent(picked)}`,
      { signal: controller.signal }).then(async (response) => {
      if (!response.ok) return;
      const item = await response.json() as IFCElement;
      if (!controller.signal.aborted && item.item_id === picked) {
        setElements((previous) => new Map(previous).set(picked, { ...previous.get(picked), ...item }));
        setDetailFetched((previous) => new Set(previous).add(`${manifest.doc_id}/${picked}`));
      }
    }).catch(() => {}).finally(() => { if (!controller.signal.aborted) setDetailsLoading(false); });
    return () => { controller.abort(); setDetailsLoading(false); };
  }, [picked, manifest, sceneUrl, detailFetched]);

  function finishEdit(edit: ItemEdit | null) {
    setEdits(viewerRef.current?.getEditState() ?? { undoCount: 0, moved: {}, materials: {} });
    advice.enqueue(edit);
  }

  /** Save the edited design as a new version (linked to the last version saved here, else the original). */
  async function saveVersion() {
    const docId = doc_id ?? manifest?.doc_id, viewer = viewerRef.current;
    if (!docId || !viewer) return;
    const snapshot = editSnapshot(viewer.getCommandState().hidden, viewer.getEditState());
    if (!snapshotHasEdits(snapshot)) return;
    const parent = saved.doc === docId ? saved.parent : 0;
    setSaved((s) => ({ ...s, busy: true, message: undefined, href: undefined }));
    try {
      const version = await saveDesignVersion(docId, snapshot, { parent, chatId: chat_id });
      setSaved({ busy: false, message: savedMessage(version), href: version.compare_url, parent: version.n, doc: docId });
    } catch (e) {
      setSaved((s) => ({ ...s, busy: false, message: e instanceof Error ? e.message : 'Could not save the version.' }));
    }
  }

  function cancelMove() {
    viewerRef.current?.endMove(true);
    dragPointer.current = null;
    setMoveItem(null);
  }

  useEffect(() => {
    if (!editing) return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        viewerRef.current?.endMove(true);
        dragPointer.current = null;
        setMoveItem(null);
      }
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [editing]);

  useEffect(() => { onReadyRef.current = onReady; }, [onReady]);
  useEffect(() => { riseStateRef.current = onRiseStateChange; }, [onRiseStateChange]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
  useEffect(() => { onPickRef.current = onPick; }, [onPick]);

  const selectItem = useCallback((itemId: string | null) => {
    setPicked(itemId);
    setSelected(itemId, '3d');
    if (itemId !== null) onPickRef.current?.(itemId);
  }, []);

  useEffect(() => {
    if (storey !== undefined) viewerRef.current?.setStorey(storey);
  }, [storey]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let active = true;
    let viewer: Viewer | null = null;
    let live: ReturnType<typeof bindLiveHighlight> | undefined;
    let liveCommands: ReturnType<typeof bindLiveCommands> | undefined;
    let unsubscribeCutaway: (() => void) | undefined;
    let unsubscribeCommands: (() => void) | undefined;
    let unsubscribeHighlight: (() => void) | undefined;
    let unsubscribeWalk: (() => void) | undefined;
    let unsubscribeBuild: (() => void) | undefined;
    setState('loading');
    setProgress({ phase: 'manifest' });
    setError('');
    setStoreys([]);
    setPicked(null);
    setManifest(null);
    setEditing(false); setMoveItem(null); dragPointer.current = null;
    setEdits({ undoCount: 0, moved: {}, materials: {} });
    setHiddenIds([]);
    setElements(new Map());
    setDetailFetched(new Set());
    setHasRoof(false);
    setServiceLabel(null);
    setLayer('all');
    setWalking(false);
    setWalkMessage('');
    setHighlightState({ highlighted: [], dimmed: 0, labels: {} });
    setAnswerKinds([]);
    setBuild(null);
    pointerStart.current = null;

    function fail(reason: unknown) {
      if (!active) return;
      const message = reason instanceof SceneLoadError && reason.status === 404
        ? reason.detail || '3D model not available for this document'
        : reason instanceof Error ? reason.message : 'Could not load the 3D scene.';
      setError(message);
      setState('error');
      onErrorRef.current?.(message);
    }

    try {
      viewer = createViewer(canvas);
      viewerRef.current = viewer;
      unsubscribeCutaway = viewer.onCutawayChange(setCutaway);
      // Chat and manual edits share one layer: refresh the panel (hidden list, Undo) on every change, remote ones too.
      unsubscribeCommands = viewer.onCommandStateChange((next) => {
        setHiddenIds(next.hidden);
        setEdits(viewer!.getEditState());
      });
      unsubscribeHighlight = viewer.onHighlightChange(() => {
        setHighlightState(viewer!.getLinkedHighlightState());
        setEdits(viewer!.getEditState());
        const items = viewer!.scene?.manifest.items;
        setAnswerKinds(viewer!.getHighlightState().highlighted.map((id) => { const it = items?.[id]; const size = itemKindKey(it) === 'drain' ? null : pipeSizeLabel(it); return it?.kind === 'room' ? `room:${roomTypeLabel(it)}` : size ? `size:${size}` : it ? itemKindKey(it) : null; }));
      });
      unsubscribeBuild = viewer.onBuildChange(setBuild);
      unsubscribeWalk = viewer.onWalkChange((next) => setWalking(next.active));
      const channel = chat_id ? createLiveHighlightClient({ chat_id }) : undefined;
      live = bindLiveHighlight(viewer, doc_id, channel);
      liveCommands = bindLiveCommands(viewer, doc_id, channel, () => chatRef.current);
      void viewer.loadScene(sceneUrl, { onProgress: (next) => { if (active) setProgress(next); } }).then((scene) => {
        if (!active) return;
        if (storey !== undefined) viewer!.setStorey(storey);
        live?.sceneReady();
        liveCommands?.sceneReady();
        setCutaway(viewer!.getCutawayState());
        setStoreys(cutawayStoreys(scene.manifest).map((entry) => entry.name));
        setHasRoof(Object.entries(scene.manifest.items).some(([id, item]) => isRoof(item.kind, scene.elements?.get(id))));
        setServiceLabel(serviceLayerLabel(scene.manifest));
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
      unsubscribeCommands?.();
      unsubscribeHighlight?.();
      unsubscribeWalk?.();
      unsubscribeBuild?.();
      setHover(null, '3d');
      live?.dispose();
      liveCommands?.dispose();
      viewer?.dispose();
      if (viewerRef.current === viewer) viewerRef.current = null;
    };
  }, [sceneUrl, chat_id]);

  useEffect(() => {
    if (state !== 'ready' || highlightRequest === undefined || commands?.length) return;
    const [ids, options] = JSON.parse(highlightRequest) as [string[], HighlightOptions];
    const viewer = viewerRef.current;
    const swap = (viewer?.getHighlightState().highlighted.length ?? 0) > 0 && ids.length > 0;
    viewer?.highlight(ids, swap ? { ...options, keepCamera: true } : { ...options, cinematic: true });
  }, [state, highlightRequest, commandRequest, sceneUrl]);

  useEffect(() => {
    if (state !== 'ready' || commandRequest === undefined) return;
    const next = JSON.parse(commandRequest) as SceneCommand[];
    for (const command of next) viewerRef.current?.applyCommand(command);
  }, [state, commandRequest, sceneUrl]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (state !== 'ready' || !viewer) return;
    // Render either source; only pointer handlers publish, so subscriptions cannot echo.
    viewer.setLinkedItems(linked.hovered, linked.selected, highlightOptions?.labels);
    setHighlightState(viewer.getLinkedHighlightState());
  }, [state, linked, highlightRequest, sceneUrl]);

  useEffect(() => {
    const canvas = canvasRef.current as LinkedViewerCanvas | null;
    if (!canvas || state !== 'ready' || new URLSearchParams(window.location.search).get('viewer3dTest') !== '1') return;
    canvas.__viewer3d = {
      state: () => viewerRef.current!.getLinkedHighlightState(),
      commandState: () => viewerRef.current!.getCommandState(),
      walk: () => viewerRef.current!.walk(),
      findings: () => viewerRef.current!.findings(),
      camera: () => { const v = viewerRef.current!; return { position: v.camera.position.toArray(), target: v.controls.target.toArray() }; },
      drawn: (id) => { for (let n: { visible: boolean; parent: unknown } | null = viewerRef.current?.scene?.items.get(id) ?? null; n; n = n.parent as typeof n) if (!n.visible) return false; return !!viewerRef.current?.scene?.items.has(id) },
      scaleY: (id) => viewerRef.current?.scene?.items.get(id)?.scale.y ?? null,
      storeyAndStep: () => ({ storey: (document.querySelector('.drawing-model select') as HTMLSelectElement | null)?.selectedOptions[0]?.textContent ?? null, step: document.querySelector('.drawing-model [data-testid="build-step-label"]')?.textContent ?? '' }),
      pick(itemId) {
        if (!viewerRef.current?.scene?.items.has(itemId)) return false;
        selectItem(itemId);
        return true;
      },
    };
    return () => { delete canvas.__viewer3d; };
  }, [state, sceneUrl, selectItem]);

  useEffect(() => {
    if (state === 'ready' && visualise) {
      viewerRef.current?.visualise((next) => riseStateRef.current?.(next));
    }
  }, [state, visualise, sceneUrl]);

  function pick(event: PointerEvent<HTMLCanvasElement>) {
    if (dragPointer.current === event.pointerId) {
      viewerRef.current?.updateMove(event.clientX, event.clientY);
      finishEdit(viewerRef.current?.endMove() ?? null);
      dragPointer.current = null; pointerStart.current = null; setMoveItem(null);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      return;
    }
    const start = pointerStart.current;
    pointerStart.current = null;
    if (viewerRef.current?.walk().active) return;
    // An orbit drag must not select the surface under the release point.
    if (!start || start.id !== event.pointerId
      || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
    if (measure3d.mode) {
      const point = viewerRef.current?.pickPoint(event.clientX, event.clientY);
      if (point) measure3d.add(point);
      return;
    }
    if (viewerRef.current?.pickFinding(event.clientX, event.clientY)) return;
    const itemId = viewerRef.current?.pick(event.clientX, event.clientY) ?? null;
    selectItem(itemId);
    if (event.shiftKey && itemId && manifest) {
      viewerRef.current?.applyCommand({ op: 'highlight', item_ids: itemsOfPickedKind(manifest, itemId) });
    }
  }

  // While the build-up plays, the selector names the storey being built, so it agrees with the step label.
  const stepStorey = build && build.phase !== 'done' ? [...storeys].sort((a, b) => b.length - a.length).find((name) => build.label.startsWith(`${name} `)) : undefined;
  const shownStorey = stepStorey ?? cutaway.activeStorey ?? '';
  const storeyIndex = storeys.indexOf(shownStorey);
  // Raster plans are extruded from pixels with default heights: say so. IFC/DXF scenes carry real geometry.
  const trust = scaleTrust(manifest?.scale_method);
  const scaleNote = trust === 'estimate' ? ESTIMATE_NOTE : trust === 'none' ? NO_SCALE_NOTE : null;
  const approximated = manifest !== null && (Boolean(manifest.plan_image)
    || (manifest as { approx?: boolean }).approx === true
    || Object.values(manifest.items).some((item) => (item.props as { approx?: unknown } | null | undefined)?.approx === true));
  const quality = qualitySummary(manifest?.quality)
  function selectStorey(name: string | null) {
    cancelMove();
    viewerRef.current?.setStorey(name);
    setPicked(null);
  }

  const saveControl: SaveVersionControl = {
    canSave: hiddenNow > 0 || Object.keys(edits.moveDelta ?? {}).length > 0 || Object.keys(edits.materials).length > 0,
    busy: saved.busy, message: saved.message, href: saved.href, onSave: () => { cancelMove(); void saveVersion(); },
  };
  return <section className="viewer3d" aria-label="3D viewer" data-state={state}
    data-highlighted-item-ids={JSON.stringify(highlightState.highlighted)}
    data-linked-selected={highlightState.highlighted.includes(linked.selected ?? '') ? linked.selected : ''}
    data-linked-hover={highlightState.highlighted.includes(linked.hovered ?? '') ? linked.hovered : ''}
    data-active-storey={cutaway.activeStorey ?? ''} data-show-roof={cutaway.showRoof} data-hidden-count={cutaway.hiddenCount}
    data-walking={walking} data-editing={editing}>
    <div className="viewer3d-toolbar">
      <label htmlFor={selectId}>Storey</label>
      <button type="button" aria-label="Previous storey" disabled={state !== 'ready' || storeyIndex <= 0}
        onClick={() => selectStorey(storeys[storeyIndex - 1])}>−</button>
      <select id={selectId} value={shownStorey} disabled={state !== 'ready'}
        onChange={(event) => selectStorey(event.target.value || null)}>
        <option value="">All storeys</option>
        {storeys.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
      <button type="button" aria-label="Next storey" disabled={state !== 'ready' || storeyIndex >= storeys.length - 1}
        onClick={() => selectStorey(storeys[storeyIndex + 1])}>+</button>
      {serviceLabel && <>
        <label htmlFor={`${selectId}-layer`}>Show</label>
        <select id={`${selectId}-layer`} aria-label="Model layer" data-testid="model-layer" value={layer} disabled={state !== 'ready'}
          onChange={(event) => { const next = event.target.value as ModelLayer; setLayer(next); viewerRef.current?.setLayer(next); }}>
          <option value="all">Floor plan + {serviceLabel.toLowerCase()}</option>
          <option value="building">Floor plan only</option>
          <option value="services">{serviceLabel} only</option>
        </select>
      </>}
      {hasRoof && <label className="viewer3d-roof-toggle">
        <input type="checkbox" checked={cutaway.showRoof}
          onChange={(event) => viewerRef.current?.setShowRoof(event.target.checked)} /> Show roof
      </label>}
      <button type="button" aria-label="Walk" aria-pressed={walking} disabled={state !== 'ready'}
        onClick={() => {
          cancelMove(); setEditing(false);
          setPicked(null); setHover(null, '3d');
          const entered = viewerRef.current?.setWalk(!walking);
          setWalkMessage(!walking && !entered ? 'No clear starting position is available on this storey.' : '');
        }}>Walk</button>
      <button type="button" aria-label="Edit" aria-pressed={editing} disabled={state !== 'ready'} onClick={() => {
        cancelMove(); viewerRef.current?.setWalk(false); setEditing(!editing);
      }}>Edit</button>
      <button type="button" disabled={state !== 'ready'} onClick={() => {
        cancelMove(); setPicked(null);
        if (viewerRef.current) clearViewerHighlights(viewerRef.current);
      }}>Clear highlights</button>
      {(() => {
        const hasEdits = hiddenNow > 0 || Object.keys(edits.moveDelta ?? {}).length > 0;
        return <button type="button" className="viewer3d-revised-btn" aria-label="Revised plan"
          disabled={state !== 'ready' || !hasEdits || !(doc_id ?? manifest?.doc_id)}
          title={hasEdits ? 'Show the 2D plan with your 3D edits applied' : 'Make an edit in 3D first'}
          onClick={() => setRevisedOpen(true)}>Revised plan</button>;
      })()}
      <FindingsPanel viewer={state === 'ready' ? viewerRef.current : null} stage={stage} />
      {/* Same controls, look and order as the 2D page toolbar (plan-inspect-tools): layer chips, ruler, inline readout. */}
      <div className="plan-inspect-tools viewer3d-plan-tools">
        {state === 'ready' && <Layers3D viewer={viewerRef.current} />}
        <Button variant="ghost" size="icon-xs" aria-label="Measure on the model" aria-pressed={!!measure3d.mode} disabled={state !== 'ready'}
          title="Measure on the model: click two points for a distance, or corners for an area"
          onClick={() => { if (measure3d.mode) measure3d.stop(); else { cancelMove(); viewerRef.current?.setWalk(false); setEditing(false); closeDetails(); measure3d.start('distance'); } }}><Ruler size={14} /></Button>
        {measure3d.mode && <span className="plan-measure-readout" role="status" aria-live="polite">
          {measure3DStatus(measure3d)}
          <Button variant="ghost" size="xs" aria-pressed={measure3d.mode === 'distance'} onClick={() => measure3d.start('distance')}>Distance</Button>
          <Button variant="ghost" size="xs" aria-pressed={measure3d.mode === 'area'} onClick={() => measure3d.start('area')}>Area</Button>
          <Button variant="ghost" size="xs" onClick={measure3d.stop}>Done</Button>
        </span>}
      </div>
    </div>
    <div ref={setStage} className="viewer3d-stage" aria-busy={state === 'loading'}>
      <canvas ref={canvasRef} tabIndex={0} aria-label="3D building model" aria-describedby={walking ? helpId : undefined}
        onPointerDownCapture={(event) => {
          if (!editing || !moveItem || event.button !== 0 || !event.isPrimary) return;
          if (viewerRef.current?.beginMove(moveItem, event.clientX, event.clientY)) {
            event.stopPropagation();
            event.currentTarget.setPointerCapture(event.pointerId);
            dragPointer.current = event.pointerId;
            pointerStart.current = null;
          }
        }}
        onPointerDown={(event) => {
          pointerStart.current = !viewerRef.current?.walk().active && event.isPrimary && event.button === 0
            ? { id: event.pointerId, x: event.clientX, y: event.clientY } : null;
        }}
        onPointerMove={(event) => {
          if (dragPointer.current === event.pointerId) {
            viewerRef.current?.updateMove(event.clientX, event.clientY); return;
          }
          if (viewerRef.current?.walk().active || event.pointerType !== 'mouse' || event.buttons !== 0 || state !== 'ready') return;
          if (measure3d.mode) { measure3d.move(viewerRef.current?.pickPoint(event.clientX, event.clientY) ?? null); if (hoverTip) setHoverTip(null); return; }
          const hovered = viewerRef.current?.pick(event.clientX, event.clientY) ?? null;
          setHover(hovered, '3d');
          const summaryItem = hovered ? planSummaries.items.get(hovered) : undefined;
          const rect = event.currentTarget.getBoundingClientRect();
          const x = event.clientX - rect.left, y = event.clientY - rect.top;
          const text = summaryItem ? planItemSummary(summaryItem, planSummaries.mPerPx) : null;
          if (!text) { if (hoverTip) setHoverTip(null); }
          else if (!hoverTip || hoverTip.text !== text || Math.hypot(hoverTip.x - x, hoverTip.y - y) > 2) setHoverTip({ text, x, y });
        }}
        onDoubleClick={() => { if (measure3d.mode === 'area') measure3d.close(); }}
        onPointerLeave={() => { setHover(null, '3d'); setHoverTip(null); }}
        onPointerUp={pick} onPointerCancel={() => { cancelMove(); pointerStart.current = null; setHover(null, '3d'); }}
        onLostPointerCapture={() => { if (dragPointer.current !== null) cancelMove(); }} />
      {state === 'loading' && <p className="viewer3d-message" role="status">
        {progress.phase === 'parse' ? 'Reading 3D model…'
          : progress.phase === 'prepare' ? 'Preparing 3D view…'
          : progress.phase === 'download' && progress.total
          ? `Loading 3D scene… ${Math.min(100, Math.round((progress.loaded ?? 0) / progress.total * 100))}%`
          : 'Loading 3D scene…'}
      </p>}
      {state === 'error' && <p className="viewer3d-message" role="alert">{error}</p>}
      {state === 'ready' && approximated && <p className="viewer3d-approx" data-testid="approx-note">3D approximated from the drawing{scaleNote && <span className="viewer3d-scale-note" data-testid="scale-note"> · {scaleNote}</span>}{quality && <span className="viewer3d-quality" data-testid="quality-badge" title={quality}>{quality}</span>}</p>}
      {state === 'ready' && answerKinds.length > 0 && <KindLegend className="kind-legend-3d" kinds={answerKinds} />}
      {picked && <output className="viewer3d-picked-overlay" aria-label="Picked item" aria-live="polite">{picked}</output>}
      {state === 'ready' && <Measure3DOverlay viewer={viewerRef.current} measure={measure3d} />}
      {state === 'ready' && !measure3d.mode && hoverTip && stage && <PlanHoverTip text={hoverTip.text} x={hoverTip.x} y={hoverTip.y} containerWidth={stage.clientWidth} containerHeight={stage.clientHeight} />}
      {walking && <WalkJoystick onMove={(x, y) => viewerRef.current?.setWalkJoystick(x, y)} />}
      {state === 'ready' && details && !editing && <ItemDetailsCard key={details.item_id} details={details}
        loading={detailsLoading} viewer={viewerRef.current} onClose={closeDetails}
        onHighlight={() => viewerRef.current?.highlight([details.item_id])} docId={doc_id ?? manifest?.doc_id ?? null} />}
    </div>
    <div className="viewer3d-footer">
      {state === 'ready' && build && <BuildSlider build={build} viewer={viewerRef.current} />}
      {state === 'ready' && editing && manifest && <EditPanel selected={picked} manifest={manifest} edits={edits}
        moving={moveItem !== null} advice={advice} hidden={hiddenIds}
        onRestore={(ids) => { cancelMove(); finishEdit(viewerRef.current?.restoreItems(ids) ?? null); }}
        save={saveControl}
        onRemove={() => { cancelMove(); if (picked) { finishEdit(viewerRef.current?.removeItem(picked) ?? null); selectItem(null); } }}
        onMove={() => { cancelMove(); if (picked && moveItem !== picked) setMoveItem(picked); }}
        onMaterial={(choice) => { cancelMove(); if (picked) finishEdit(viewerRef.current?.changeMaterial(picked, choice) ?? null); }}
        onUndo={() => { cancelMove(); finishEdit(viewerRef.current?.undoEdit() ?? null); }}
        onReset={() => { cancelMove(); finishEdit(viewerRef.current?.resetEdits() ?? null); }}
        onHighlight={(ids) => {
          cancelMove(); selectItem(null);
          viewerRef.current?.applyCommand({ op: 'highlight', item_ids: ids });
        }} />}
      {walking && <p id={helpId}>WASD / arrow keys to move · Drag to look · Q/E or PageUp/Down for storeys · Esc to return to orbit</p>}
      {walkMessage && <p role="status">{walkMessage}</p>}
    </div>
  {revisedOpen && (doc_id ?? manifest?.doc_id) && viewerRef.current && <RevisedPlanDialog docId={(doc_id ?? manifest?.doc_id)!} manifest={manifest}
    removed={viewerRef.current.getCommandState().hidden} moved={viewerRef.current.getEditState().moveDelta ?? {}}
    save={saveControl} onClose={() => setRevisedOpen(false)} />}
  </section>;
}

export default Viewer3D;
