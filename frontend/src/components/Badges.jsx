
import React from 'react'
import { AlertTriangle, AlertCircle, Info, ShieldAlert } from 'lucide-react'

const SEVERITY_CONFIG = {
  critical: { cls: 'badge-critical', icon: ShieldAlert, label: 'Critical' },
  error:    { cls: 'badge-error',    icon: AlertCircle,  label: 'Error' },
  warning:  { cls: 'badge-warning',  icon: AlertTriangle, label: 'Warning' },
  info:     { cls: 'badge-info',     icon: Info,          label: 'Info' },
}

export default function SeverityBadge({ severity }) {
  const key = (severity || 'info').toLowerCase()
  const cfg = SEVERITY_CONFIG[key] || SEVERITY_CONFIG.info
  const Icon = cfg.icon
  return (
    <span className={cfg.cls}>
      <Icon size={11} className="mr-1" />
      {cfg.label}
    </span>
  )
}

export function RiskBadge({ level }) {
  const key = (level || 'low').toLowerCase()
  const cls = key === 'high' ? 'badge-high' : key === 'medium' ? 'badge-medium' : 'badge-low'
  return <span className={cls}>{key.charAt(0).toUpperCase() + key.slice(1)} Risk</span>
}

export function CategoryBadge({ category }) {
  const colors = {
    security:        'bg-[rgba(220,38,38,0.08)] text-[#DC2626] border-[rgba(220,38,38,0.15)]',
    correctness:     'bg-[rgba(234,88,12,0.08)] text-[#EA580C] border-[rgba(234,88,12,0.15)]',
    performance:     'bg-[rgba(29,78,216,0.08)] text-[#60a5fa] border-[rgba(29,78,216,0.15)]',
    maintainability: 'bg-[rgba(245,158,11,0.08)] text-[#F59E0B] border-[rgba(245,158,11,0.15)]',
    style:           'bg-[rgba(34,197,94,0.08)] text-[#22c55e] border-[rgba(34,197,94,0.15)]',
  }
  const c = colors[(category || '').toLowerCase()] || colors.maintainability
  return <span className={`badge border ${c}`}>{category}</span>
}
