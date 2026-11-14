import { useEffect, useState } from 'react'
import { HelpMarkdown } from './help-markdown'
import './help-screen.css'

export function HelpScreen() {
  const [markdown, setMarkdown] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setUnavailable(false)
    fetch(`${import.meta.env.BASE_URL}judges.md`, { signal: controller.signal }).then(async (response) => {
      if (!response.ok || response.headers.get('content-type')?.includes('text/html')) throw new Error('Guide unavailable')
      const text = await response.text()
      // A missing static file can return the SPA's HTML with status 200.
      if (!text.trim() || /^\s*(?:<!doctype\s+html|<html\b)/i.test(text)) throw new Error('Guide unavailable')
      if (!controller.signal.aborted) setMarkdown(text)
    }).catch(() => { if (!controller.signal.aborted) setUnavailable(true) })
    return () => controller.abort()
  }, [attempt])

  return <section className="help-screen" aria-label="Judges’ guide">
    {markdown === null ? <div className="help-loading">
      <p role="status">The guide is loading.</p>
      {unavailable && <button type="button" className="button button-outline button-size-default" onClick={() => setAttempt((value) => value + 1)}>Retry loading guide</button>}
    </div> : <article className="help-guide"><HelpMarkdown markdown={markdown} /></article>}
  </section>
}
