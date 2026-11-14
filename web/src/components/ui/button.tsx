import type { ButtonHTMLAttributes } from 'react'

export function Button({ className = '', variant = 'ghost', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'raised'
}) {
  return <button className={`button button-${variant} ${className}`} {...props} />
}
