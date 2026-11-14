import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, X } from 'lucide-react'
import { linkedApi, propertyValue, type ItemPlace, type LinkedItem } from '../lib/linked'
import './item-panel.css'

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
            <h3>IFC properties</h3>
            {Object.keys(item.props).length ? <dl className="item-properties">{Object.entries(item.props).map(([key, value]) => <div key={key} data-property={key}><dt>{key}</dt><dd>{propertyValue(value)}</dd></div>)}</dl> : <p>No IFC properties supplied.</p>}
            <h3>Appears in</h3>
            {item.places.length ? <ul className="item-places">{item.places.map((place, index) => <li key={`${place.doc_id}-${place.page}-${index}`}>
              <button type="button" onClick={() => onOpenPlace(place, item)}><span>{place.storey || place.doc_id}<small>Page {place.page}{!place.bbox_px ? ' · No box supplied' : ''}</small></span><ArrowUpRight size={16} /></button>
            </li>)}</ul> : <p>No drawing locations supplied.</p>}
          </>}
      </div>
    </section>
  </>
}
