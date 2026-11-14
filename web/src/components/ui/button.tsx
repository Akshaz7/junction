import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'default' | 'primary' | 'secondary' | 'outline' | 'ghost' | 'link' | 'raised' | 'outline-primary' | 'destructive' | 'ghost-destructive' | 'outline-destructive' | 'sidebar'
export type ButtonSize = 'xs' | 'sm' | 'default' | 'lg' | 'xl' | '2xl' | 'icon-xs' | 'icon-sm' | 'icon' | 'icon-lg' | 'icon-xl' | 'icon-2xl'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  shape?: 'default' | 'pill'
}

export function Button({ className = '', variant = 'default', size = 'default', shape = 'default', type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={`button button-${variant} button-size-${size} button-shape-${shape} ${className}`} {...props} />
}
