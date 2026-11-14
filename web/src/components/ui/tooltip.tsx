import { cloneElement, useId, useState, type ReactElement } from 'react'

export function Tooltip({ content, children }: {
  content: string
  children: ReactElement<{ 'aria-describedby'?: string }>
}) {
  const id = useId()
  const [dismissed, setDismissed] = useState(false)
  return <span className="tooltip" onKeyDown={(event) => { if (event.key === 'Escape') setDismissed(true) }} onBlur={() => setDismissed(false)} onMouseLeave={() => setDismissed(false)}>
    {cloneElement(children, { 'aria-describedby': [children.props['aria-describedby'], id].filter(Boolean).join(' ') })}
    <span className="tooltip-content" role="tooltip" id={id} style={dismissed ? { display: 'none' } : undefined}>{content}</span>
  </span>
}
