import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { chatLive } from '../lib/chat-live'
import { retryMessage, subscribeApiRetry } from '../lib/api'
import './connection-pill.css'

/** Data stays mounted across routes; the portal keeps connection feedback visible on every screen. */
export function ConnectionPill({ enabled = true, live = chatLive }: { enabled?: boolean; live?: Pick<typeof chatLive, 'subscribe'> }) {
  const [reconnecting, setReconnecting] = useState(false)
  const [retry, setRetry] = useState(retryMessage)
  useEffect(() => subscribeApiRetry(setRetry), [])
  useEffect(() => {
    if (!enabled) { setReconnecting(false); return }
    // A slow initial connection may never emit a close event (e.g. constructor failure).
    const pending = setTimeout(() => setReconnecting(true), 1_000)
    const unsubscribe = live.subscribe((event) => {
      if (event.type === 'connected' || event.type === 'disconnected') {
        clearTimeout(pending)
        setReconnecting(event.type === 'disconnected')
      }
    })
    return () => { clearTimeout(pending); unsubscribe() }
  }, [enabled, live])
  const message = retry || (reconnecting ? 'Reconnecting…' : '')
  return message && typeof document !== 'undefined'
    ? createPortal(<div className="connection-pill" role="status" aria-live="polite">{message}</div>, document.body)
    : null
}
