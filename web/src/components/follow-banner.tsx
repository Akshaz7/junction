import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Radio, X } from 'lucide-react'
import { getFollow, onFollowChange, setFollow } from '../lib/chat-follow'

export function useFollow() {
  const [on, setOn] = useState(getFollow)
  useEffect(() => onFollowChange(setOn), [])
  return [on, setFollow] as const
}

/** Toggle for History / overview: auto-open chats that other devices start. */
export function FollowToggle() {
  const [on, set] = useFollow()
  return <label className="follow-toggle"><input type="checkbox" role="switch" checked={on} onChange={(event) => set(event.target.checked)} /> Follow other devices</label>
}

/** Non-intrusive notice over any page: a question was asked on another device. */
export function FollowBanner({ incoming, onOpen, onDismiss }: { incoming: { chatId: string; question: string } | null; onOpen: (chatId: string) => void; onDismiss: () => void }) {
  const [follow, setFollowing] = useFollow()
  if (!incoming) return null
  const q = incoming.question.length > 70 ? `${incoming.question.slice(0, 70)}…` : incoming.question
  return createPortal(<div className="follow-banner" role="status" aria-live="polite" data-testid="follow-banner">
    <Radio size={15} aria-hidden="true" />
    <span className="follow-text">New question from another device: &lsquo;{q}&rsquo;</span>
    <button type="button" className="follow-open" onClick={() => onOpen(incoming.chatId)}>Open</button>
    <label className="follow-auto"><input type="checkbox" checked={follow} onChange={(event) => setFollowing(event.target.checked)} /> Follow</label>
    <button type="button" className="follow-close" aria-label="Dismiss" onClick={onDismiss}><X size={14} /></button>
  </div>, document.body)
}
