import { useCallback, useMemo, useState, type CSSProperties, type JSX } from 'react'
import { Button } from '../ui'
import { kindStyle } from '../../lib/kind-colors'
import './plan-layers.css'

export type LayerKey = 'wall' | 'door' | 'window' | 'room' | 'fixture' | 'text'
export interface LayerItem { id: string; kind: string; bbox: [number, number, number, number]; polygon?: [number, number][] | null }

export const LAYER_KEYS: readonly LayerKey[] = ['wall', 'door', 'window', 'room', 'fixture', 'text']
const LAYER_LABELS: Record<LayerKey, string> = { wall: 'Walls', door: 'Doors', window: 'Windows', room: 'Rooms', fixture: 'Fixtures', text: 'Text' }
/** Chip swatch colour per layer; fixtures use toilet colour as the representative (shapes use each item's own kind colour). */
const LAYER_COLOR_KIND: Record<LayerKey, string> = { wall: 'wall', door: 'door', window: 'window', room: 'room', fixture: 'toilet', text: 'other' }
const STORAGE_KEY = 'plan-layers'

/** door/window/wall/room/text map to themselves; everything else is a fixture. */
export function layerOf(kind: string): LayerKey {
  const k = (kind ?? '').toLowerCase()
  return k === 'door' || k === 'window' || k === 'wall' || k === 'room' || k === 'text' ? k : 'fixture'
}

function readShown(): Set<LayerKey> {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    return new Set(Array.isArray(parsed) ? parsed.filter((k): k is LayerKey => (LAYER_KEYS as readonly unknown[]).includes(k)) : [])
  } catch { return new Set() }
}

function writeShown(shown: Set<LayerKey>) {
  try { globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify([...shown])) } catch { /* storage unavailable */ }
}

/** Which layers are on; remembered per browser. */
export function usePlanLayers(): { shown: Set<LayerKey>; toggle(key: LayerKey): void; clear(): void } {
  const [shown, setShown] = useState<Set<LayerKey>>(readShown)
  const toggle = useCallback((key: LayerKey) => setShown((prev) => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    writeShown(next)
    return next
  }), [])
  const clear = useCallback(() => setShown(() => { const next = new Set<LayerKey>(); writeShown(next); return next }), [])
  return { shown, toggle, clear }
}

function groupItems(items: LayerItem[]): Map<LayerKey, LayerItem[]> {
  const groups = new Map<LayerKey, LayerItem[]>(LAYER_KEYS.map((k) => [k, []]))
  for (const item of items) groups.get(layerOf(item.kind))!.push(item)
  return groups
}

/** Toolbar chips with counts; hidden layers with 0 items are not shown. */
export function PlanLayerChips({ items, shown, onToggle }: { items: LayerItem[]; shown: Set<LayerKey>; onToggle(key: LayerKey): void }): JSX.Element | null {
  const groups = useMemo(() => groupItems(items), [items])
  const keys = LAYER_KEYS.filter((k) => groups.get(k)!.length > 0 || shown.has(k))
  if (!keys.length) return null
  return (
    <div className="plan-layer-chips" role="group" aria-label="Plan layers">
      {keys.map((key) => {
        const count = groups.get(key)!.length
        const on = shown.has(key)
        return (
          <Button key={key} variant="ghost" size="xs" className={`plan-layer-chip ${on ? 'is-on' : ''}`} aria-pressed={on} data-layer={key}
            aria-label={`${on ? 'Hide' : 'Show'} ${LAYER_LABELS[key].toLowerCase()} (${count})`}
            style={{ '--kind-color': kindStyle(LAYER_COLOR_KIND[key]).color } as CSSProperties}
            onClick={() => onToggle(key)}>
            <span className="plan-layer-swatch" aria-hidden="true" />{LAYER_LABELS[key]} {count}
          </Button>
        )
      })}
    </div>
  )
}

function Shape({ item, selected }: { item: LayerItem; selected: boolean }) {
  const style = { '--kind-color': kindStyle(item.kind).color } as CSSProperties
  const cls = `plan-layer-shape ${layerOf(item.kind) === 'room' ? 'is-room' : ''} ${selected ? 'is-selected' : ''}`
  const poly = item.polygon
  if (poly && poly.length >= 3) {
    return <polygon className={cls} style={style} data-item-id={item.id} data-kind={item.kind} vectorEffect="non-scaling-stroke" points={poly.map(([x, y]) => `${x},${y}`).join(' ')} />
  }
  const [x0, y0, x1, y1] = item.bbox
  return <rect className={cls} style={style} data-item-id={item.id} data-kind={item.kind} vectorEffect="non-scaling-stroke"
    x={Math.min(x0, x1)} y={Math.min(y0, y1)} width={Math.abs(x1 - x0)} height={Math.abs(y1 - y0)} />
}

/** Rendered INSIDE the page-pixel <svg viewBox="0 0 W H"> of the viewer, below answer highlights. pointer-events none. */
export function PlanLayerShapes({ items, shown, selectedId }: { items: LayerItem[]; shown: Set<LayerKey>; selectedId?: string | null }): JSX.Element | null {
  const groups = useMemo(() => groupItems(items), [items])
  // Rooms first so smaller items draw on top of their fills.
  const order: LayerKey[] = ['room', 'wall', 'fixture', 'window', 'door', 'text']
  const visible = order.filter((k) => shown.has(k) && groups.get(k)!.length > 0)
  if (!visible.length) return null
  return (
    <g className="plan-layers" aria-hidden="true" data-testid="plan-layers">
      {visible.map((key) => (
        <g key={key} className="plan-layer" data-layer={key}>
          {groups.get(key)!.map((item) => <Shape key={item.id} item={item} selected={item.id === selectedId} />)}
        </g>
      ))}
    </g>
  )
}
