import { ReactNode } from 'react'

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'cyan' | 'outline'

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  size?: 'sm' | 'md'
  pulse?: boolean
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-surface-muted text-neutral-300 border-surface-border',
  success: 'bg-success-500/15 text-success-500 border-success-500/30',
  warning: 'bg-warning-500/15 text-warning-500 border-warning-500/30',
  danger: 'bg-danger-500/15 text-danger-500 border-danger-500/30',
  info: 'bg-navy-500/15 text-navy-400 border-navy-500/30',
  cyan: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  outline: 'bg-transparent text-neutral-400 border-neutral-600',
}

export default function Badge({ children, variant = 'default', size = 'sm', pulse = false, className = '' }: BadgeProps) {
  const sizeStyles = size === 'sm' ? 'text-[10px] px-2 py-0.5' : 'text-xs px-2.5 py-1'
  return (
    <span className={`
      inline-flex items-center gap-1.5 rounded-full font-medium border
      ${variantStyles[variant]} ${sizeStyles} ${className}
    `}>
      {pulse && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
        </span>
      )}
      {children}
    </span>
  )
}
