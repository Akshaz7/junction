import { useEffect, useId, useRef, useState } from 'react'
import { Clock, MessageSquareShare, Plus, X } from 'lucide-react'
import { Button } from './ui'
import { overviewDate } from '../lib/overview'
import { FollowToggle } from './follow-banner'
import './follow-banner.css'
import { PairPhoneButton } from './pair-phone'
import { useDialogFocus } from '../lib/use-dialog-focus'

interface HistoryChat { id: string; title: string | null; created_at: string }

export function ChatHeaderActions({ chatId, onNew }: { chatId: string | null; onNew: () => void }) {
  const [open, setOpen] = useState(false)
  const [chats, setChats] = useState<HistoryChat[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const host = useRef<HTMLDivElement>(null)
  const historyButton = useRef<HTMLButtonElement>(null)
  const dialog = useRef<HTMLElement>(null)
  const titleId = useId()
  useDialogFocus(open, dialog, historyButton, () => setOpen(false))

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 3000)
    return () => clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setLoading(true); setError(''); setChats([])
    fetch('/api/chats', { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error('Saved chats could not be loaded. Please try again.')
      const data = await response.json() as { chats: HistoryChat[] }
      if (!controller.signal.aborted) setChats([...data.chats].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0)))
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Saved chats could not be loaded.')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    function outside(event: PointerEvent) { if (!host.current?.contains(event.target as Node)) setOpen(false) }
    const close = () => setOpen(false)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('hashchange', close)
    return () => {
      controller.abort()
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('hashchange', close)
    }
  }, [open])

  async function share() {
    if (!chatId) { setToast('Start a chat to share a link.'); return }
    const url = new URL(window.location.href)
    url.hash = `/chat/${encodeURIComponent(chatId)}`
    try {
      if (window.matchMedia('(max-width: 800px)').matches && navigator.share) {
        await navigator.share({ title: 'Hologram', url: url.href })
      } else {
        await navigator.clipboard.writeText(url.href)
        setToast('Link copied')
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) setToast('Could not share the link. Please try again.')
    }
  }

  return <div className="chat-header-actions" ref={host}>
    <Button variant="raised" aria-label="New chat" onClick={() => { setOpen(false); setToast(''); onNew() }}><Plus size={16} /><span>New</span></Button>
    <button type="button" className="button button-raised button-size-default" ref={historyButton} aria-label="History" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? 'chat-history' : undefined} onClick={() => setOpen((value) => !value)}><Clock size={16} /><span>History</span></button>
    <Button variant="raised" aria-label="Share" onClick={() => void share()}><MessageSquareShare size={16} /><span>Share</span></Button>
    <PairPhoneButton />
    {open && <section ref={dialog} id="chat-history" className="chat-history-popover" role="dialog" aria-modal="true" aria-label="Chat history" aria-labelledby={titleId} tabIndex={-1}>
      <header><strong><span id={titleId} className="sr-only">Chat history</span><span aria-hidden="true">History</span></strong><FollowToggle /><button type="button" aria-label="Close chat history" onClick={() => setOpen(false)}><X size={16} /></button></header>
      {loading ? <p role="status">Loading chats…</p> : error ? <p role="alert">{error}</p> : chats.length ? <ul>{chats.map((chat) => <li key={chat.id}>
        <a href={`#/chat/${encodeURIComponent(chat.id)}`} aria-current={chat.id === chatId ? 'page' : undefined} onClick={() => setOpen(false)}><span>{chat.title || 'Untitled chat'}</span><time dateTime={chat.created_at}>{overviewDate(chat.created_at)}</time></a>
      </li>)}</ul> : <p>No saved chats yet. <Button variant="raised" onClick={() => { setOpen(false); setToast(''); onNew() }}>New chat</Button></p>}
    </section>}
    {toast && <div className="chat-action-toast" role="status">{toast}</div>}
  </div>
}
