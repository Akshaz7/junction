import { useEffect, useState } from 'react'
import { ScanLine } from 'lucide-react'
import { arHandler, showOnTable } from '../lib/ar-bridge'
import { workspaceApi } from '../lib/api'
import './show-on-table.css'

export function ShowOnTableButton({ docId, itemIds = [], chatId, sceneAvailable }: {
  docId: string; itemIds?: string[]; chatId?: string | null; sceneAvailable?: boolean
}) {
  const [phone, setPhone] = useState(false)
  const [available, setAvailable] = useState(false)
  const native = typeof window !== 'undefined' && !!arHandler(window)
  useEffect(() => {
    if (!native) return
    const media = window.matchMedia('(max-width: 800px)')
    const update = () => setPhone(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [native])
  useEffect(() => {
    setAvailable(false)
    if (!native || !phone) return
    if (sceneAvailable !== undefined) { setAvailable(sceneAvailable); return }
    const controller = new AbortController()
    // Metadata currently omits scene fields; check the existing scene artifact without extruding.
    workspaceApi.hasScene(docId, controller.signal).then((exists) => {
      if (!controller.signal.aborted) setAvailable(exists)
    }).catch(() => { /* Unavailable scenes have no AR action. */ })
    return () => controller.abort()
  }, [docId, native, phone, sceneAvailable])
  if (!native || !phone || !available) return null
  return <button type="button" className="show-on-table" onClick={() => showOnTable({ doc_id: docId, item_ids: itemIds, chat_id: chatId ?? undefined })}>
    <ScanLine size={15} aria-hidden="true" /><span>Show on table</span>
  </button>
}
