interface SovereignLogoProps {
  size?: number
  animate?: boolean
  className?: string
}

export default function SovereignLogo({ size = 32, animate = true, className = '' }: SovereignLogoProps) {
  const ringRadius = 14
  const ringStroke = 2.8
  const gapAngle = 22
  const segmentCount = 4

  const circumference = 2 * Math.PI * ringRadius
  const segmentLength = circumference / segmentCount
  const gapLength = (gapAngle / 360) * circumference
  const arcLength = segmentLength - gapLength

  const hexPoints = (cx: number, cy: number, r: number) => {
    const pts: string[] = []
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i - Math.PI / 2
      pts.push(`${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`)
    }
    return pts.join(' ')
  }

  const segments = Array.from({ length: segmentCount }, (_, i) => {
    const rotation = (360 / segmentCount) * i - 90
    const dashOffset = -(gapLength / 2)
    return { rotation, dashOffset, index: i }
  })

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`${className} ${animate ? 'sovereign-logo' : ''}`}
    >
      {/* Outer ring segments */}
      {segments.map(({ rotation, dashOffset, index }) => (
        <circle
          key={index}
          cx="16"
          cy="16"
          r={ringRadius}
          stroke="var(--color-navy-800, #1e293b)"
          strokeWidth={ringStroke}
          strokeLinecap="round"
          strokeDasharray={`${arcLength} ${gapLength}`}
          strokeDashoffset={dashOffset}
          transform={`rotate(${rotation} 16 16)`}
          className={animate ? `ring-segment ring-segment-${index}` : ''}
          style={{ fill: 'none' }}
        />
      ))}

      {/* Inner hexagon */}
      <polygon
        points={hexPoints(16, 16, 5.5)}
        fill="var(--color-navy-800, #1e293b)"
        className={animate ? 'hexagon' : ''}
      />

      {/* Blue accent dot */}
      <circle
        cx="26"
        cy="12"
        r="1.8"
        fill="var(--color-cyan-500, #06b6d4)"
        className={animate ? 'accent-dot' : ''}
      />
    </svg>
  )
}
