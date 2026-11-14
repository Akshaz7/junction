import { useEffect, useState } from 'react'
import { apiFetch } from '../../lib/api'

export interface RoomLabel { id: string; box: [number, number, number, number]; name: string; detail: string }

interface RoomItem { item_id: string; kind?: string; label?: string; bbox_px: number[] | null; props?: { area_m2?: number } }
interface ElementRow { item_id: string; kind?: string; type_name?: string; props?: { long_name?: string } }

/** Rooms that have a real name: a plan map room joined to its element by id. Rooms without a name are skipped. */
export function buildRoomLabels(items: RoomItem[], elements: ElementRow[]): RoomLabel[] {
  const named = new Map(elements.filter((row) => row.kind === 'room').map((row) => [row.item_id, row.props?.long_name?.trim() || row.type_name?.trim() || '']))
  return items.flatMap((item) => {
    const name = named.get(item.item_id)
    if (!name || item.kind !== 'room' || !item.bbox_px || item.bbox_px.length < 4) return []
    const area = item.props?.area_m2
    const detail = [item.label, typeof area === 'number' ? `${area.toFixed(1)} m²` : ''].filter(Boolean).join(' · ')
    return [{ id: item.item_id, box: item.bbox_px.slice(0, 4) as RoomLabel['box'], name, detail }]
  })
}

/** Name and area for each room of an IFC plan, drawn under the numbered boxes. Labels scale with the drawing and hide when the room is too small. */
export function RoomLabels({ docId, page, width, height, scale }: { docId: string; page: number; width: number; height: number; scale: number }) {
  const [rooms, setRooms] = useState<RoomLabel[]>([])
  useEffect(() => {
    const controller = new AbortController()
    setRooms([])
    const read = async (path: string) => { const response = await apiFetch(path, { signal: controller.signal }); return response.ok ? response.json() : null }
    const base = `/api/docs/${encodeURIComponent(docId)}`
    Promise.all([read(`${base}/planmap/${page}`), read(`${base}/files/elements.json`)]).then(([planmap, elements]) => {
      if (!controller.signal.aborted && planmap?.items && elements?.elements) setRooms(buildRoomLabels(planmap.items, elements.elements))
    }).catch(() => {})
    return () => controller.abort()
  }, [docId, page])
  if (!rooms.length) return null
  return <svg className="room-labels" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
    {rooms.map((room) => {
      const [x, y, right, bottom] = room.box
      const w = right - x, h = bottom - y
      const text = Math.max(room.name.length, room.detail.length)
      const font = Math.min(w / (text * 0.6), h / 3.2, 60)
      if (font * scale < 6) return null
      return <text key={room.id} className="room-label" x={x + w / 2} y={y + h / 2} textAnchor="middle" fontSize={font}>
        <tspan x={x + w / 2} dy={-font * 0.15}>{room.name}</tspan>
        <tspan x={x + w / 2} dy={font * 1.15} className="room-label-detail">{room.detail}</tspan>
      </text>
    })}
  </svg>
}
