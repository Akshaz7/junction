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
  const [arReason, setArReason] = useState<string | null>(null)
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
    setArReason(null)
    if (!native || !phone) return
    const controller = new AbortController()
    if (sceneAvailable !== undefined) setAvailable(sceneAvailable)
    // A scene whose AR export failed carries the reason in its manifest: say so rather than hiding the button.
    workspaceApi.arStatus(docId, controller.signal).then((status) => {
      if (controller.signal.aborted) return
      if (status.exists && !status.usdz) { setAvailable(false); setArReason(status.reason) }
      else if (sceneAvailable === undefined) setAvailable(status.exists)
    }).catch(() => { /* Unavailable scenes have no AR action. */ })
    return () => controller.abort()
  }, [docId, native, phone, sceneAvailable])
  if (native && phone && arReason) return <span className="show-on-table-unavailable" role="note">AR not available for this file: {arReason}</span>
  if (!native || !phone || !available) return null
  return <button type="button" className="show-on-table" onClick={() => showOnTable({ doc_id: docId, item_ids: itemIds, chat_id: chatId ?? undefined })}>
    <ScanLine size={15} aria-hidden="true" /><span>Show on table</span>
  </button>
}
