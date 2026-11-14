import { useEffect, useId, useRef, useState } from 'react'
import { Smartphone, X } from 'lucide-react'
import qrcode from 'qrcode-generator'
import { Button } from './ui'
import { ensurePairCode, getPairings, onPairingChange, pairCodeFromHash, addPairing, pairLink, unpair } from '../lib/pairing'
import { useDialogFocus } from '../lib/use-dialog-focus'

function qrSvg(text: string): string {
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true })
}

/** Opens `#/pair?code=…` on the phone: stores the pairing, then shows the chat. Mounted once in the app shell. */
export function PairingLanding() {
  const [notice, setNotice] = useState('')
  useEffect(() => {
    function check() {
      const code = pairCodeFromHash(window.location.hash)
      if (code === null) return
      const ok = addPairing(code)
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#/chat`)
      window.dispatchEvent(new HashChangeEvent('hashchange'))
      setNotice(ok ? 'Paired. New chats from your other device open here.' : 'That pairing link is not valid.')
    }
    check()
    window.addEventListener('hashchange', check)
    return () => window.removeEventListener('hashchange', check)
  }, [])
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(''), 5000)
    return () => clearTimeout(timer)
  }, [notice])
  return notice ? <div className="pair-notice" role="status" data-testid="pair-notice">{notice}</div> : null
}

export function PairPhoneButton() {
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const [paired, setPaired] = useState(getPairings().length > 0)
  const host = useRef<HTMLSpanElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const dialog = useRef<HTMLElement>(null)
  const dialogId = useId()
  const titleId = useId()
  useDialogFocus(open && !!code, dialog, trigger, () => setOpen(false))
  useEffect(() => onPairingChange(() => setPaired(getPairings().length > 0)), [])
  useEffect(() => {
    if (!open) return
    setCode(ensurePairCode())
    function outside(event: PointerEvent) { if (!host.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  const link = code ? pairLink(code) : ''
  return <span className="pair-phone" ref={host}>
    <Button variant="raised" aria-label="Pair a phone" title="Pair a phone" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? dialogId : undefined} onClick={(event) => { trigger.current = event.currentTarget; setOpen((value) => !value) }}><Smartphone size={16} /><span>{paired ? 'Paired' : 'Pair a phone'}</span></Button>
    {open && code && <section ref={dialog} id={dialogId} className="pair-popover" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header><strong id={titleId}>Pair a phone</strong><button type="button" aria-label="Close pairing" onClick={() => setOpen(false)}><X size={16} /></button></header>
      <div className="pair-qr" role="img" aria-label="QR code to pair a phone" dangerouslySetInnerHTML={{ __html: qrSvg(link) }} />
      <p>Scan with the phone camera. Chats you start here then open and stream on the phone, with no other step.</p>
      <input readOnly className="pair-link" aria-label="Pairing link" value={link} onFocus={(event) => event.currentTarget.select()} />
      <Button variant="raised" onClick={() => { unpair(); setOpen(false) }}>Unpair</Button>
    </section>}
  </span>
}
