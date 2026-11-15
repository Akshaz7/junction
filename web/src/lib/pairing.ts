/** Device pairing: a shared random code makes chats created on one paired device "known" on the other.
 *  Codes live in localStorage on both devices; the server only records which chats were created under a code. */
import { setFollow } from './chat-follow'
import { isKnownChat, rememberChat } from './known-chats'

const KEY = 'hologram.pair-codes'
let memory: string[] = []

function read(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) ?? 'null')
    return Array.isArray(parsed) ? parsed.filter((c): c is string => typeof c === 'string' && /^[A-Za-z0-9]{6,32}$/.test(c)) : memory
  } catch { return memory }
}
function write(codes: string[]) {
  memory = codes
  try { window.localStorage.setItem(KEY, JSON.stringify(codes)) } catch { /* memory only */ }
  window.dispatchEvent(new CustomEvent('hologram:pairing', { detail: codes.length }))
}

export const getPairings = (): string[] => read()
export const isPaired = (): boolean => read().length > 0

export function newPairCode(): string {
  const bytes = new Uint8Array(8)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => 'abcdefghjkmnpqrstuvwxyz23456789'[b % 31]).join('')
}

/** Store a code (this device scanned it, or the laptop created it). Following paired devices is on from then. */
export function addPairing(code: string) {
  if (!/^[A-Za-z0-9]{6,32}$/.test(code)) return false
  const codes = read()
  if (!codes.includes(code)) write([...codes, code])
  setFollow(true)
  return true
}

const HOST_KEY = 'hologram.pair-hosted'
let hostedMemory = ''
const hostedCode = (): string => { try { return window.localStorage.getItem(HOST_KEY) ?? hostedMemory } catch { return hostedMemory } }
/** True while this device only shows its own QR code: no phone has been confirmed, so never claim "Paired". */
export const isWaitingForPhone = (): boolean => { const hosted = hostedCode(); return !!hosted && read().length > 0 && read().every((code) => code === hosted) }

export function unpair() {
  hostedMemory = ''
  try { window.localStorage.removeItem(HOST_KEY) } catch { /* memory only */ }
  write([])
}

export function onPairingChange(listener: () => void) {
  window.addEventListener('hologram:pairing', listener)
  return () => window.removeEventListener('hologram:pairing', listener)
}

/** Ensure this device has a code to show as a QR code. */
export function ensurePairCode(): string {
  const [first] = read()
  if (first) return first
  const code = newPairCode()
  hostedMemory = code
  try { window.localStorage.setItem(HOST_KEY, code) } catch { /* memory only */ }
  addPairing(code)
  return code
}

export function pairLink(code: string, origin = window.location.origin): string {
  return `${origin}/#/pair?code=${code}`
}

/** What the pairing QR encodes: opens the native Hologram app, which loads the web pairing link in its web shell. */
export function pairAppLink(code: string): string {
  return `hologram://pair?code=${encodeURIComponent(code)}`
}

export function pairCodeFromHash(hash: string): string | null {
  const match = hash.match(/^#\/pair\?(.*)$/)
  return match ? new URLSearchParams(match[1]).get('code') : null
}

/** The deployed backend answers in 1-3 s under load, so a short timeout silently dropped the pairing: allow 8 s (never below 4 s) and retry a failed call once. */
async function call(method: 'GET' | 'POST', code: string, chatId: string): Promise<Response | null> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetch(`/api/pair/${code}/chats/${encodeURIComponent(chatId)}`, { method, signal: AbortSignal.timeout(8000) })
      if (response.ok || (response.status < 500 && response.status !== 429)) return response
    } catch { /* retry once */ }
  }
  return null
}

/** Tell the server this chat was created on a paired device. Awaited before the first question so the other device can check it. */
export async function registerChat(chatId: string): Promise<void> {
  await Promise.all(read().map((code) => call('POST', code, chatId)))
}

/** True when this device knows the chat, or the server says a paired device created it (then it is remembered). */
export async function isPairedChat(chatId: string): Promise<boolean> {
  if (isKnownChat(chatId)) return true
  for (const code of read()) {
    const response = await call('GET', code, chatId)
    // No answer (timeout, 429, 5xx) means "not proven": never follow a chat on a guess, other users' chats share this socket.
    if (response?.ok && (await response.json() as { paired?: boolean }).paired) { rememberChat(chatId); return true }
  }
  return false
}

async function proofFor(code: string, chatId: string): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${code}:${chatId}`))
    return Array.from(new Uint8Array(digest).slice(0, 8), (b) => b.toString(16).padStart(2, '0')).join('')
  } catch { return null }
}

/** A live "pair.chat" event carries a hash of (code, chat id): if one of our codes matches, the chat is ours with no server call. */
export async function acceptPairProof(chatId: string, proof: string): Promise<boolean> {
  for (const code of read()) {
    if ((await proofFor(code, chatId)) === proof) { rememberChat(chatId); return true }
  }
  return false
}
