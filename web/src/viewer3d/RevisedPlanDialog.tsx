import { useEffect, useMemo, useRef, useState } from 'react';
import { workspaceApi } from '../lib/api';
import { planRevision, type RevisionItem, type RevisionPlan } from '../lib/revised-plan';
import { renderRevised, REVISED_TITLE } from '../lib/revised-plan-canvas';
import type { SceneManifest } from './scene';

interface PageData { page: number; size: { w: number; h: number }; items: RevisionItem[]; mPerPx: number | null }
type Mode = 'revised' | 'original' | 'wipe';

export function RevisedPlanDialog({ docId, manifest, removed, moved, onClose }: {
  docId: string; manifest: SceneManifest | null; removed: readonly string[];
  moved: Record<string, [number, number]>; onClose: () => void;
}) {
  const [pages, setPages] = useState<PageData[] | null>(null);
  const [error, setError] = useState('');
  const [page, setPage] = useState<number | null>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [mode, setMode] = useState<Mode>('revised');
  const [wipe, setWipe] = useState(50);
  const revisedRef = useRef<HTMLCanvasElement>(null);
  const originalRef = useRef<HTMLCanvasElement>(null);
  const removedKey = removed.join('|'), movedKey = JSON.stringify(moved);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const doc = await workspaceApi.getDocument(docId).catch(() => null);
        const count = Math.max(1, Math.min(doc?.pages ?? 1, 30));
        const maps = await Promise.all(Array.from({ length: count }, (_, i) =>
          workspaceApi.getPlanMap(docId, i + 1, controller.signal).catch(() => null)));
        const loaded: PageData[] = [];
        maps.forEach((map, i) => {
          if (!map) return;
          const raw = map as unknown as { image?: { w: number; h: number }; scale?: { m_per_px?: number };
            items: (RevisionItem & { props?: { tag?: string } })[] };
          loaded.push({ page: i + 1, size: raw.image ?? { w: 0, h: 0 }, mPerPx: raw.scale?.m_per_px ?? null,
            items: raw.items.map((it) => ({ ...it, kind: it.kind ?? manifest?.items[it.item_id]?.kind,
              tag: it.tag ?? it.props?.tag ?? manifest?.items[it.item_id]?.tag })) });
        });
        if (controller.signal.aborted) return;
        setPages(loaded);
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Could not load the plan.'); }
    })();
    return () => controller.abort();
  }, [docId, manifest]);

  const plans = useMemo(() => (pages ?? []).map((p) => ({ ...p,
    plan: planRevision({ size: p.size, items: p.items, removed, moved, mPerPx: p.mPerPx }) })).filter((p) => p.plan.rows.length),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [pages, removedKey, movedKey]);
  const current = plans.find((p) => p.page === page) ?? plans[0];
  const plan: RevisionPlan | undefined = current?.plan;

  useEffect(() => {
    if (!current) return;
    const controller = new AbortController();
    let url = '';
    setImage(null);
    void workspaceApi.getPageImage(docId, current.page, controller.signal).then((blob) => {
      url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => { if (!controller.signal.aborted) setImage(img); };
      img.onerror = () => setError('Could not load the page image.');
      img.src = url;
    }).catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Could not load the page image.'); });
    return () => { controller.abort(); if (url) setTimeout(() => URL.revokeObjectURL(url), 1000); };
  }, [docId, current?.page]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!image || !plan) return;
    if (revisedRef.current) renderRevised(revisedRef.current, image, plan, { revised: true });
    if (originalRef.current) renderRevised(originalRef.current, image, plan, { revised: false });
  }, [image, plan, mode]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  function download() {
    const canvas = revisedRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = `${docId}-revised.png`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }, 'image/png');
  }

  return <div className="revised-plan-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="revised-plan-dialog" role="dialog" aria-modal="true" aria-label="Revised plan" data-testid="revised-plan-dialog">
      <div className="revised-plan-head">
        <h2>{REVISED_TITLE}</h2>
        <button type="button" onClick={download} disabled={!image || !plan}>Download PNG</button>
        <button type="button" onClick={onClose} aria-label="Close revised plan">Close</button>
      </div>
      <div className="revised-plan-bar">
        {(['revised', 'original', 'wipe'] as Mode[]).map((m) => <button key={m} type="button" aria-pressed={mode === m}
          onClick={() => setMode(m)}>{m === 'revised' ? 'Revised' : m === 'original' ? 'Original' : 'Wipe'}</button>)}
        {mode === 'wipe' && <input type="range" min={0} max={100} value={wipe} aria-label="Wipe between original and revised"
          onChange={(e) => setWipe(Number(e.target.value))} />}
        {plans.length > 1 && plans.map((p) => <button key={p.page} type="button" aria-pressed={p.page === current?.page}
          onClick={() => setPage(p.page)}>Page {p.page}</button>)}
        <span>{plan ? `${plan.rows.length} change${plan.rows.length === 1 ? '' : 's'}` : ''}</span>
      </div>
      <div className="revised-plan-stage">
        {error && <p role="alert">{error}</p>}
        {!error && !pages && <p role="status">Building the revised plan…</p>}
        {!error && pages && !plan && <p role="status">The edited items are not drawn on this document's 2D pages, so there is nothing to revise.</p>}
        {plan && <div style={{ position: 'relative' }}>
          <canvas ref={revisedRef} data-testid="revised-plan-canvas" aria-label="Revised plan"
            style={{ display: mode === 'original' ? 'none' : 'block' }} />
          <canvas ref={originalRef} aria-label="Original plan" data-testid="original-plan-canvas"
            style={mode === 'original' ? { display: 'block' }
              : mode === 'wipe' ? { display: 'block', position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', clipPath: `inset(0 ${100 - wipe}% 0 0)` }
              : { display: 'none' }} />
        </div>}
      </div>
    </div>
  </div>;
}
