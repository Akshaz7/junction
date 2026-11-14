import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { Mesh, MeshStandardMaterial } from 'three'
import { apiFetch } from '../lib/api'
import type { Bbox } from '../lib/types'
import type { Viewer } from '../viewer3d/viewer'
import type { FileDocument } from './data-screen'
import { Button } from './ui'

const Viewer3D = lazy(() => import('../viewer3d/Viewer3D').then((module) => ({ default: module.Viewer3D })))
type ChangeType = 'added' | 'removed' | 'moved' | 'resized' | 'property_changed'
type Source = { doc_id: string; item_id: string; page: number; bbox_px: Bbox | null; bbox_m: number[][] | null; storey: string | null }
type Change = { change_id: string; n: number; type: ChangeType; kind: string; description: string; storey: string | null; page: number; v1: Source | null; v2: Source | null; property_details?: { label: string; old: string; new: string }[] }
type Counts = Record<ChangeType, number> & { total: number }
export type PairComparison = {
  doc_a: string; doc_b: string; status: 'ready' | 'partial' | 'unavailable'; method: string; note: string; warnings: string[]
  inventory_a: number; inventory_b: number; matched_items: number
  generated_for_demo?: boolean
  summary: (Counts & { affected_items: number; by_kind: Record<string, Counts>; by_storey: Record<string, Counts> }) | null
  changes: Change[]
  versions: { doc_id: string; label: string; kind?: string }[]
  pages: { page: number; image_a: { w: number; h: number }; image_b: { w: number; h: number }; page_image_a: string | null; page_image_b: string | null }[]
}
const typeLabels: Record<ChangeType, string> = { added: 'Added', removed: 'Removed', moved: 'Moved', resized: 'Resized', property_changed: 'Properties changed' }
const kindLabel = (kind: string) => ({ mep_other: 'Services items', proxy: 'Building items', other: 'Other items', space: 'Rooms', stairs: 'Stairs' }[kind] || `${kind.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())}s`)

/** Revision hints only select a suggestion; users confirm by pressing Compare. */
export function revisionTitle(title: string) {
  return title.normalize('NFKC').toLocaleLowerCase().replace(/\.(?:ifc|dxf|dwg|pdf|png|jpe?g)$/i, '')
    .replace(/(?<!\d)20\d{2}[-._ ]?\d{2}[-._ ]?\d{2}(?!\d)/g, ' ')
    .replace(/[\s_()\[\].-]*(?:rev(?:ision)?|ver(?:sion)?|v)[\s_.-]*[\p{L}\d]+[\s)\]]*$/u, '')
    .replace(/\s+/g, ' ').replace(/[\s_.-]+$/g, '').trim()
}

export function suggestVersions(docs: FileDocument[]): [string, string] {
  for (const doc of docs) {
    const versions = (doc.versions || []).filter((v) => docs.some((d) => d.doc_id === v.doc_id))
    if (versions.length >= 2) return [versions[versions.length - 2].doc_id, versions[versions.length - 1].doc_id]
  }
  const groups = new Map<string, FileDocument[]>()
  for (const doc of docs) {
    const base = revisionTitle(doc.title)
    if (!base) continue
    const key = `${doc.folder || doc.source}|${doc.kind}|${base}`
    groups.set(key, [...(groups.get(key) || []), doc])
  }
  const candidates = [...groups.values()].filter((g) => g.length > 1)
  for (const group of candidates) {
    group.sort((a, b) => (a.date || a.updated_at || a.title).localeCompare(b.date || b.updated_at || b.title, undefined, { numeric: true }))
  }
  const group = candidates[0]
  return group ? [group[group.length - 2].doc_id, group[group.length - 1].doc_id] : ['', '']
}

function ComparisonModel({ docId, source, side, label }: { docId: string; source: Source | null; side: 'v1' | 'v2'; label: string }) {
  const [viewer, setViewer] = useState<Viewer | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!viewer) return
    const ids = source ? [source.item_id] : []
    const recolor = () => {
      const color = getComputedStyle(document.documentElement).getPropertyValue(side === 'v1' ? '--change-removed' : '--change-added').trim()
      if (!color) return
      for (const id of ids) viewer.scene?.items.get(id)?.traverse((object) => {
        if (!(object as Mesh).isMesh) return
        const mesh = object as Mesh
        for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
          const surface = material as MeshStandardMaterial
          surface.color?.set(color); surface.emissive?.set(color)
        }
      })
    }
    const stop = viewer.onHighlightChange(recolor)
    viewer.highlight(ids, { labels: source ? { [source.item_id]: label } : {}, cameraTargetItemId: source?.item_id, keepCamera: true })
    recolor()
    return stop
  }, [viewer, source, side, label])
  return <div className={`revision-model ${side}`}>
    <Suspense fallback={<p role="status">Loading model…</p>}><Viewer3D doc_id={docId} storey={null} onReady={setViewer} onError={setError} /></Suspense>
    {error && <p role="status">{error}</p>}
    {!source && <p className="revision-absent">This item is absent in this version.</p>}
  </div>
}

export function VersionPairCompare({ docs, onOpen }: { docs: FileDocument[]; onOpen: (open: boolean) => void }) {
  const [a, setA] = useState(''), [b, setB] = useState('')
  const [result, setResult] = useState<PairComparison | null>(null)
  const [loading, setLoading] = useState(false), [error, setError] = useState('')
  const [selected, setSelected] = useState(''), [side, setSide] = useState<'v1' | 'v2'>('v2')
  const [page, setPage] = useState(1), [storey, setStorey] = useState('')
  const [failedImages, setFailedImages] = useState<string[]>([])
  const request = useRef<AbortController | null>(null)
  const touched = useRef(false), linked = useRef(false)
  useEffect(() => () => request.current?.abort(), [])
  useEffect(() => {
    if (touched.current || !docs.length) return
    const query = new URLSearchParams(window.location.hash.split('?')[1] || '')
    const qa = query.get('a'), qb = query.get('b')
    if (qa && qb && qa !== qb && docs.some((d) => d.doc_id === qa) && docs.some((d) => d.doc_id === qb)) {
      setA(qa); setB(qb)
      if (!linked.current) { linked.current = true; touched.current = true; void compare(qa, qb) }
    } else {
      const pair = suggestVersions(docs); setA(pair[0]); setB(pair[1])
    }
  }, [docs]) // eslint-disable-line react-hooks/exhaustive-deps

  function reset() {
    request.current?.abort(); setResult(null); setError(''); setLoading(false); onOpen(false)
  }
  async function compare(aa = a, bb = b) {
    request.current?.abort()
    const controller = new AbortController(); request.current = controller
    setResult(null); setError(''); setLoading(true); onOpen(true); setFailedImages([]); setStorey('')
    try {
      const response = await apiFetch('/api/changes/compare', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_a: aa, doc_b: bb }), signal: controller.signal })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Comparison failed (${response.status}).`)
      if (controller.signal.aborted) return
      if (!Array.isArray(data.changes) || !Array.isArray(data.versions)) throw new Error('Comparison data is unavailable.')
      const comparison = data as PairComparison
      setResult(comparison); setSelected(comparison.changes[0]?.change_id || ''); setPage(comparison.pages[0]?.page || 1)
      setSide(comparison.changes[0]?.type === 'removed' ? 'v1' : 'v2')
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Comparison could not be loaded.')
    } finally { if (!controller.signal.aborted) setLoading(false) }
  }
  const active = result?.changes.find((c) => c.change_id === selected)
  const sheet = result?.pages.find((p) => p.page === page)
  const changes = result?.changes.filter((c) => (!sheet || c.page === page) && (!storey || (c.storey || 'Storey not recorded') === storey)) || []
  const groups = useMemo(() => {
    const grouped = new Map<string, Change[]>()
    for (const change of changes) grouped.set(change.kind, [...(grouped.get(change.kind) || []), change])
    return [...grouped].sort(([x], [y]) => x.localeCompare(y))
  }, [changes])
  const source = active?.[side] || null
  const choose = (change: Change) => { setSelected(change.change_id); setPage(change.page); if (!change[side]) setSide(change.v1 ? 'v1' : 'v2') }

  return <div className="revision-pair">
    <form className="revision-pair-controls" onSubmit={(event) => { event.preventDefault(); void compare() }}>
      <div><strong>Compare two versions</strong><p>Choose an earlier and a later file to see what was added, removed or changed.</p></div>
      {(['A', 'B'] as const).map((label) => <label key={label}>Version {label}<select aria-label={`Version ${label}`} value={label === 'A' ? a : b}
        onChange={(event) => { touched.current = true; reset(); (label === 'A' ? setA : setB)(event.target.value) }}>
        <option value="">Choose a document</option>{docs.map((doc) => <option key={doc.doc_id} value={doc.doc_id}>{doc.title} · {doc.kind.toUpperCase()}</option>)}
      </select></label>)}
      <Button variant="raised" type="submit" disabled={!a || !b || a === b || loading}>{loading ? 'Comparing…' : 'Compare versions'}</Button>
      {a && a === b && <small role="status">Choose two different versions.</small>}
    </form>
    {loading && <p className="revision-pair-message" role="status">Comparing both versions…</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
    {result && <div className="revision-pair-result">
      <header><h2>{result.summary ? `${result.summary.total} ${result.summary.total === 1 ? 'change' : 'changes'} across ${result.summary.affected_items} ${result.summary.affected_items === 1 ? 'item' : 'items'}` : 'Comparison unavailable'}</h2><Button variant="ghost" onClick={reset}>Back to change feed</Button></header>
      {result.generated_for_demo && <p className="revision-pair-message">Includes content generated for demo.</p>}
      {result.summary && <div className="revision-tiles" aria-label="Change summary">{(Object.keys(typeLabels) as ChangeType[]).map((type) => <div key={type} className={type}><strong>{result.summary![type]}</strong><span>{typeLabels[type]}</span></div>)}</div>}
      {result.warnings.map((warning) => <p key={warning} className="revision-pair-message">{warning}</p>)}
      {result.summary && <>
        <div className="revision-result-controls">
          {result.pages.length > 1 && <label>Page<select aria-label="Comparison page" value={page} onChange={(event) => { const n = Number(event.target.value); setPage(n); setSelected(result.changes.find((c) => c.page === n)?.change_id || '') }}>{result.pages.map((p) => <option key={p.page} value={p.page}>{p.page}</option>)}</select></label>}
          <label>Storey<select aria-label="Comparison storey" value={storey} onChange={(event) => { const value = event.target.value; setStorey(value); const next = result.changes.find((c) => (!sheet || c.page === page) && (!value || (c.storey || 'Storey not recorded') === value)); if (next) choose(next); else setSelected('') }}><option value="">All storeys</option>{Object.keys(result.summary.by_storey).map((s) => <option key={s} value={s}>{s} · {result.summary!.by_storey[s].total}</option>)}</select></label>
          <span className="revision-colour-key"><i className="removed" />Earlier / removed<i className="added" />Later / added</span>
        </div>
        <div className="revision-result-body">
          <div className="revision-evidence">
            {result.method === 'ifc-globalid' ? <>
              <div className="compare-segments" role="group" aria-label="Model version">{(['v1', 'v2'] as const).map((s, i) => <button type="button" key={s} aria-pressed={side === s} onClick={() => setSide(s)}>Version {i === 0 ? 'A' : 'B'}</button>)}</div>
              <ComparisonModel key={side === 'v1' ? result.doc_a : result.doc_b} docId={side === 'v1' ? result.doc_a : result.doc_b} source={source} side={side} label={active ? String(active.n) : ''} />
            </> : sheet && <div className="revision-two-sheets">{(['v1', 'v2'] as const).map((s, i) => {
              const image = i === 0 ? sheet.image_a : sheet.image_b, url = i === 0 ? sheet.page_image_a : sheet.page_image_b
              return <figure key={`${sheet.page}-${s}`}><figcaption>Version {i === 0 ? 'A' : 'B'} · {result.versions[i].label}</figcaption>
                {url && image?.w > 0 && image?.h > 0 && !failedImages.includes(url) ? <div className="revision-source-sheet" style={{ aspectRatio: `${image.w}/${image.h}` }}>
                  <img src={url} alt={`Version ${i === 0 ? 'A' : 'B'}, page ${page}`} onError={() => setFailedImages((old) => [...old, url])} />
                  {changes.map((c) => { const box = c[s]?.bbox_px; return box && <button type="button" key={c.change_id} className={`change-region ${s === 'v1' ? 'removed' : 'added'}`} aria-label={`Change ${c.n} in version ${i === 0 ? 'A' : 'B'}`} data-active={selected === c.change_id || undefined} onClick={() => choose(c)}
                    style={{ left: `${box[0] / image.w * 100}%`, top: `${box[1] / image.h * 100}%`, width: `${(box[2] - box[0]) / image.w * 100}%`, height: `${(box[3] - box[1]) / image.h * 100}%` }}><b>{c.n}</b></button> })}
                </div> : <p className="revision-pair-message">Page preview unavailable for this version.</p>}
              </figure>
            })}</div>}
            <div className="revision-proof" aria-label="How we know"><strong>How we know</strong><p>Found: {result.inventory_a} items in version A, {result.inventory_b} in version B.</p><p>Checked: {result.note}</p><small>{result.status === 'ready' ? result.method === 'ifc-globalid' ? 'Verified against indexed model data' : 'Cross-checked against aligned drawing items' : 'Estimate · review the limitations above'}</small></div>
          </div>
          <aside className="revision-change-list" aria-label="Changes by kind">{groups.map(([kind, rows]) => <section key={kind}><h3>{kindLabel(kind)} <span>{rows.length}</span></h3>{rows.map((c) => <button type="button" key={c.change_id} aria-pressed={selected === c.change_id} onClick={() => choose(c)}><span className={`revision-change-type ${c.type}`}>{c.n} · {typeLabels[c.type]}</span><p>{c.description}</p>{c.property_details?.map((detail) => <p key={detail.label}>{detail.label}: {detail.old} → {detail.new}</p>)}{c.storey && <small>{c.storey}</small>}</button>)}</section>)}
            {!changes.length && <p>{result.summary.total === 0 ? 'No differences found in the compared data.' : 'No changes on this page or storey.'}</p>}
            {active && <div className="revision-source-links"><strong>Source versions for change {active.n}</strong>{([active.v1, active.v2]).map((s, i) => <a key={i} href={`#/data?doc=${encodeURIComponent(result.versions[i].doc_id)}`}>Version {i === 0 ? 'A' : 'B'}{s ? ` · Page ${s.page}` : ' · Item absent'}</a>)}</div>}
          </aside>
        </div>
      </>}
    </div>}
  </div>
}
