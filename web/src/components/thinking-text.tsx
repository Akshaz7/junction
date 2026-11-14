import type { CSSProperties } from 'react'

/** A 60 ms glyph wave, with the reference's six-glyph falloff and four-glyph rest. */
export function ThinkingText({ text }: { text: string }) {
  const cycle = (Array.from(text).length + 11) * 60
  const wave = `thinking-wave-${Array.from(text).length}`
  return <span className="thinking-text" aria-label={text} style={{ '--thinking-cycle': `${cycle}ms` } as CSSProperties}>
    <style>{`@keyframes ${wave}{0%,100%{color:color-mix(in oklab,var(--muted-foreground) 85%,var(--background));text-shadow:none}${60 / cycle * 100}%{color:var(--foreground);text-shadow:0 0 .6px currentColor}${420 / cycle * 100}%{color:color-mix(in oklab,var(--muted-foreground) 85%,var(--background));text-shadow:none}}`}</style>
    <span aria-hidden="true">{Array.from(text).map((glyph, index) => <span key={`${text}-${index}`} style={{ animationName: wave, animationDelay: `${index * 60}ms` }}>{glyph}</span>)}</span>
  </span>
}
