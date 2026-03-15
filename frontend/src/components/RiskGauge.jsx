
import React from 'react'
import { Shield } from 'lucide-react'

const RISK_COLORS = {
  low:      { ring: '#22c55e', bg: '#22c55e' },
  medium:   { ring: '#F59E0B', bg: '#F59E0B' },
  high:     { ring: '#DC2626', bg: '#DC2626' },
  critical: { ring: '#DC2626', bg: '#DC2626' },
}

export default function RiskGauge({ riskScore }) {
  if (!riskScore || riskScore.error) return null

  const { level, score, confidence, contributing_factors, model_type } = riskScore
  const pct = Math.round(score * 100)
  const c = RISK_COLORS[level] || RISK_COLORS.low
  const circumference = 2 * Math.PI * 40
  const dashOffset = circumference - (score * circumference)

  return (
    <div className="card p-6 animate-slide-up">
      <div className="flex items-center gap-2 mb-5">
        <Shield size={16} className="text-[#9ca3af]" />
        <h3 className="section-label !mb-0">Risk Assessment</h3>
      </div>

      <div className="flex items-center gap-8">
        {/* Circular gauge */}
        <div className="relative w-24 h-24 flex-shrink-0">
          <svg className="w-24 h-24 -rotate-90" viewBox="0 0 96 96">
            <circle cx="48" cy="48" r="40" fill="none"
              stroke="rgba(255,255,255,0.06)" strokeWidth="6" />
            <circle cx="48" cy="48" r="40" fill="none"
              stroke={c.ring} strokeWidth="6" strokeLinecap="round"
              strokeDasharray={circumference} strokeDashoffset={dashOffset}
              style={{ transition: 'stroke-dashoffset 1s ease-out' }} />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold" style={{ color: c.ring }}>{pct}</span>
            <span className="text-[10px] text-[#4b5563] uppercase tracking-[0.2em] font-mono">score</span>
          </div>
        </div>

        {/* Details */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-lg font-bold uppercase tracking-wide" style={{ color: c.ring }}>
              {level}
            </span>
            <span className="text-xs text-[#4b5563]">
              {Math.round(confidence * 100)}% confidence · {model_type}
            </span>
          </div>
          <ul className="space-y-1.5">
            {(contributing_factors || []).slice(0, 4).map((f, i) => (
              <li key={i} className="text-xs text-[#9ca3af] flex items-start gap-2">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: c.bg, opacity: 0.5 }} />
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
