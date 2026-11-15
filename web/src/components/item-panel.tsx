import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, X } from 'lucide-react'
import { linkedApi, propertyValue, type ItemPlace, type LinkedItem } from '../lib/linked'
import './item-panel.css'
import { WallDetails } from './wall-details'
import { wallAskHref } from '../lib/wall-details'
import { itemAskHref, measuredRows, measureProvenance, sourceProps, withoutWallDetailRows } from '../lib/item-measures'

type ItemWithQuantities = LinkedItem & { quantities?: Record<string, unknown> | null }

export function ItemPanel({ docId, itemId, sheet, onClose, onOpenPlace }: {
  docId: string; itemId: string; sheet: boolean; onClose: () => void
  onOpenPlace: (place: ItemPlace, item: LinkedItem) => void
}) {
  const [item, setItem] = useState<LinkedItem | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const panel = useRef<HTMLElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => { close.current?.focus() }, [itemId, docId])
  useEffect(() => {
    const controller = new AbortController()
    setItem(null); setError('')
    linkedApi.get(docId, itemId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setItem(value)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Item details could not be loaded.')
    })
    return () => controller.abort()
  }, [docId, itemId, retry])
  return <>
    {sheet && <div className="item-panel-scrim" aria-hidden="true" onClick={onClose} />}
    <section ref={panel} className={`item-panel ${sheet ? 'item-panel-sheet' : ''}`} role={sheet ? 'dialog' : 'region'} aria-modal={sheet || undefined} aria-label="Item details"
      onKeyDown={(event) => {
        if (event.key === 'Escape') { event.stopPropagation(); onClose() }
        if (event.key !== 'Tab' || !sheet) return
        const controls = panel.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
        if (!controls?.length) return
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
        event.stopPropagation()
      }}>
      <header><h2>Item details</h2><button ref={close} type="button" className="button button-ghost button-size-icon" aria-label="Close item details" onClick={onClose}><X size={18} /></button></header>
      <div className="item-panel-content">
        {error ? <div role="alert"><p>{error}</p><button className="button button-raised" onClick={() => setRetry((value) => value + 1)}>Try again</button></div>
          : !item ? <p role="status">Loading item details…</p> : <>
            <dl className="item-summary">{([
              ['Kind', item.kind], ['Tag', item.tag], ['Name', item.name], ['Storey', item.storey], ['Type', item.type_name],
            ] as const).map(([key, value]) => <div key={key}><dt>{key}</dt><dd data-field={key.toLowerCase()}>{value || 'Not supplied'}</dd></div>)}</dl>
            <ItemMeasures item={item} />
            {item.wall_details && <WallDetails wall={item.wall_details} />}
            {item.kind === 'wall'
              ? <a className="wall-ask item-ask" href={wallAskHref(docId, item.tag || item.item_id)}>Ask about this wall</a>
              : <a className="item-ask" href={itemAskHref(docId, item.kind, item.tag || item.name || item.item_id)}>Ask about this {item.kind || 'item'}</a>}
            <SourceProperties props={item.props ?? {}} />
            <h3>Appears in</h3>
            {item.places.length ? <ul className="item-places">{item.places.map((place, index) => <li key={`${place.doc_id}-${place.page}-${index}`}>
              <button type="button" onClick={() => onOpenPlace(place, item)}><span>{place.storey || place.doc_id}<small>Page {place.page}{!place.bbox_px ? ' · No box supplied' : ''}</small></span><ArrowUpRight size={16} /></button>
            </li>)}</ul> : <p>No drawing locations supplied.</p>}
          </>}
      </div>
    </section>
  </>
}

type RelationRef = { item_id: string; kind?: string | null; label?: string | null; number?: string | null }
type Relations = { rooms?: RelationRef[]; room?: RelationRef | null; wall?: RelationRef | null; openings?: RelationRef[]; walls?: (RelationRef & { length_m?: number | null })[]; counts?: Record<string, number> }

function refName(ref: RelationRef) { return [ref.number, ref.label].filter(Boolean).join(' ') || ref.item_id }

/** Plain geometry over the same plan map (engine/linked.py relations): what this item connects to or contains. */
function relationRows(relations: Relations | null | undefined): { label: string; value: string }[] {
  if (!relations) return []
  const rows: { label: string; value: string }[] = []
  if (relations.rooms?.length) rows.push({ label: relations.rooms.length > 1 ? 'Rooms' : 'Room', value: relations.rooms.map(refName).join(', ') })
  if (relations.room) rows.push({ label: 'In room', value: refName(relations.room) })
  if (relations.wall) rows.push({ label: 'In wall', value: relations.wall.item_id })
  if (relations.counts && Object.keys(relations.counts).length) rows.push({ label: 'Contains', value: Object.entries(relations.counts).map(([kind, n]) => `${n} ${kind}${n === 1 ? '' : 's'}`).join(', ') })
  if (relations.openings?.length) rows.push({ label: 'Openings', value: relations.openings.map((ref) => ref.item_id).join(', ') })
  if (relations.walls?.length) rows.push({ label: 'Walls', value: `${relations.walls.length}` })
  return rows
}

function ItemMeasures({ item }: { item: ItemWithQuantities }) {
  const extra = item as ItemWithQuantities & { measures?: Record<string, unknown> | null; relations?: Relations | null }
  // Engine measures fill gaps only: never repeat a value the drawing's own props already give.
  const shown = new Set(Object.keys(item.props ?? {}))
  const derived = Object.fromEntries(Object.entries(extra.measures ?? {}).filter(([key, value]) => typeof value === 'number' && key !== 'm_per_px'
    && !shown.has(key) && !(key === 'area_measured_m2' && shown.has('area_m2_geom'))))
  const all = measuredRows(item.kind, item.props ?? {}, { ...derived, ...(item.quantities ?? {}) })
  // WallDetails (2D panel and 3D card) already shows length and thickness.
  const rows = item.wall_details ? withoutWallDetailRows(all) : all
  const provenance = measureProvenance(item.props ?? {})
  const related = relationRows(extra.relations)
  return <>
    {rows.length > 0 && <><h3>Measured</h3>
      <dl className="item-measured">{rows.map((row) => <div key={row.key} data-measure={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></>}
    {provenance && <p className="item-provenance">{provenance}</p>}
    {related.length > 0 && <><h3>On this plan</h3>
      <dl className="item-measured" data-testid="item-relations">{related.map((row) => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></>}
  </>
}

function SourceProperties({ props }: { props: Record<string, unknown> }) {
  const rest = Object.entries(sourceProps(props))
  return <>
    <h3>Source properties</h3>
    {rest.length ? <dl className="item-properties">{rest.map(([key, value]) => <div key={key} data-property={key}><dt>{key}</dt><dd>{propertyValue(value)}</dd></div>)}</dl> : <p>No additional source properties supplied.</p>}
  </>
}

/** The same deterministic facts as the 2D item panel (measured values, where they come from, what the item
 * connects to), for the 3D item card. Fetches the linked item itself; renders nothing until it has data. */
export function LinkedItemFacts({ docId, itemId }: { docId: string; itemId: string }) {
  const [item, setItem] = useState<ItemWithQuantities | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    setItem(null)
    linkedApi.get(docId, itemId, controller.signal).then((value) => { if (!controller.signal.aborted) setItem(value) }).catch(() => {})
    return () => controller.abort()
  }, [docId, itemId])
  return item ? <div className="linked-item-facts" data-testid="linked-item-facts"><ItemMeasures item={item} /></div> : null
}
