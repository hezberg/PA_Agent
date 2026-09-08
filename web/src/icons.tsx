// Inline SVG icon set — 16px, 1.5 stroke, inherits currentColor.
interface IconProps {
  className?: string
}

const base = {
  width: 16,
  height: 16,
  viewBox: '0 0 16 16',
  fill: 'none' as const,
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export function GearIcon(_: IconProps) {
  return (
    <svg {...base} aria-hidden>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M12.4 3.6L11 5M5 11l-1.4 1.4" />
    </svg>
  )
}

export function CandleIcon(_: IconProps) {
  return (
    <svg {...base} aria-hidden>
      <path d="M3.5 2v3M3.5 8v6M8 1v6M8 10v5M12.5 3v5M12.5 11v2" />
      <rect x="2" y="5" width="3" height="3" rx="0.5" />
      <rect x="6.5" y="7" width="3" height="3" rx="0.5" />
      <rect x="11" y="8" width="3" height="3" rx="0.5" />
    </svg>
  )
}

export function ChevronLeftIcon(_: IconProps) {
  return (
    <svg {...base} aria-hidden>
      <path d="M10 4L6 8l4 4" />
    </svg>
  )
}

export function ChevronDownIcon(_: IconProps) {
  return (
    <svg {...base} aria-hidden>
      <path d="M4 6l4 4 4-4" />
    </svg>
  )
}

export function CloseIcon(_: IconProps) {
  return (
    <svg {...base} aria-hidden>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  )
}
