import { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  hover?: boolean
  glow?: boolean
}

export function Card({ children, className = '', hover = false, glow = false }: CardProps) {
  return (
    <div className={`
      bg-surface-raised border border-surface-border rounded-xl
      ${hover ? 'hover:border-cyan-700/50 hover:shadow-card-hover transition-all duration-200' : 'shadow-card'}
      ${glow ? 'card-glow' : ''}
      ${className}
    `}>
      {children}
    </div>
  )
}

export function CardHeader({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`px-5 py-4 border-b border-surface-border ${className}`}>
      {children}
    </div>
  )
}

export function CardContent({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`p-5 ${className}`}>
      {children}
    </div>
  )
}

export function StatCard({ label, value, icon, sub, color = 'cyan', flash }: {
  label: string
  value: string | number
  icon: string
  sub?: string
  color?: 'cyan' | 'blue' | 'green' | 'yellow' | 'red'
  flash?: boolean
}) {
  const colorMap = {
    cyan: { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/20' },
    blue: { bg: 'bg-navy-500/10', text: 'text-navy-400', border: 'border-navy-500/20' },
    green: { bg: 'bg-success-500/10', text: 'text-success-500', border: 'border-success-500/20' },
    yellow: { bg: 'bg-warning-500/10', text: 'text-warning-500', border: 'border-warning-500/20' },
    red: { bg: 'bg-danger-500/10', text: 'text-danger-500', border: 'border-danger-500/20' },
  }
  const c = colorMap[color]

  return (
    <Card hover className="relative overflow-hidden">
      <CardContent>
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-neutral-400 uppercase tracking-wider">{label}</p>
            <p className={`text-2xl font-bold text-white mt-1 transition-all duration-300 ${flash ? 'scale-110 text-cyan-400' : ''}`}>
              {value}
            </p>
            {sub && <p className="text-[10px] text-neutral-500 mt-0.5">{sub}</p>}
          </div>
          <div className={`w-10 h-10 rounded-lg ${c.bg} flex items-center justify-center text-lg transition-all duration-300 ${flash ? `${c.bg} scale-110` : ''}`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
