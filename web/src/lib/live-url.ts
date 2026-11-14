/** WebSocket base for live sync. Vercel cannot proxy WebSockets, so a deployed build may point at the
 * API host directly (VITE_LIVE_ORIGIN=https://<api-host>); otherwise same origin (dev, preview, Aiven). */
export function liveSocketUrl(query = ''): string {
  const configured = (import.meta.env.VITE_LIVE_ORIGIN as string | undefined)?.trim()
  const base = configured
    ? configured.replace(/^http/, 'ws').replace(/\/$/, '')
    : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  return `${base}/ws${query}`
}
