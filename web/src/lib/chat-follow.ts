/** "Follow" preference: auto-open chats started on another device. Off by default, kept per browser. */
const KEY = 'hologram.follow-chats'

export function getFollow(): boolean {
  try { return window.localStorage.getItem(KEY) === '1' } catch { return false }
}

export function setFollow(on: boolean) {
  try { window.localStorage.setItem(KEY, on ? '1' : '0') } catch { /* private mode: keep it in memory only */ }
  window.dispatchEvent(new CustomEvent('hologram:follow', { detail: on }))
}

export function onFollowChange(listener: (on: boolean) => void) {
  const handler = (event: Event) => listener(!!(event as CustomEvent<boolean>).detail)
  window.addEventListener('hologram:follow', handler)
  return () => window.removeEventListener('hologram:follow', handler)
}
