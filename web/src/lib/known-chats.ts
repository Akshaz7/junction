/** Chat ids this browser created or opened (also via a shared link or History). Only these can raise the "another device" notice. */
const KEY = 'hologram.known-chats'
const MAX = 200
let memory: string[] = []

function read(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : memory
  } catch { return memory }
}

export function isKnownChat(id: string): boolean {
  return read().includes(id) || memory.includes(id)
}

export function rememberChat(id: string) {
  if (!id || isKnownChat(id)) return
  memory = [...memory, id].slice(-MAX)
  try { window.localStorage.setItem(KEY, JSON.stringify([...read(), id].slice(-MAX))) } catch { /* private mode: memory only */ }
}
