import type { HTMLAttributes } from 'react'

export function Badge({ className = '', variant = 'neutral', ...props }: HTMLAttributes<HTMLSpanElement> & {
  variant?: 'neutral' | 'success' | 'warning' | 'info'
}) {
  return <span className={`badge badge-${variant} ${className}`} {...props} />
}
