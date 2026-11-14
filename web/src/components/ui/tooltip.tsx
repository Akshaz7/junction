import { cloneElement, useId, type ReactElement } from 'react'

export function Tooltip({ content, children }: {
  content: string
  children: ReactElement<{ 'aria-describedby'?: string }>
}) {
  const id = useId()
  return <span className="tooltip">
    {cloneElement(children, { 'aria-describedby': [children.props['aria-describedby'], id].filter(Boolean).join(' ') })}
    <span className="tooltip-content" role="tooltip" id={id}>{content}</span>
  </span>
}
