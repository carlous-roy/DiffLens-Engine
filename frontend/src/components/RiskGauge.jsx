import React from 'react'
import { Shield } from 'lucide-react'

const RISK_COLORS = {
  low:    { ring: '#22c55e', bg: '#22c55e' },
  medium: { ring: '#F59E0B', bg: '#F59E0B' },
  high:   { ring: '#DC2626', bg: '#DC2626' },
}

const MODEL_LABELS = {
  gradient_boosting: 'gradient boosting',
  heuristic: 'heuristic fallback',
}

function pct(value) {
  return `${Math.round(value * 100)}%`
}

function formatValue(value) {
  if (value === null || value === undefined) return 'n/a'
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

/** Risk assessment card: final score, its two sources and the model's top attributions. */
export default function RiskGauge({ riskScore }) {
  if (!riskScore || riskScore.error) return null

  const {
    level, score, model_type, model_probability, static_score,
    contributing_factors, attributions, warnings,
  } = riskScore
  const c = RISK_COLORS[level] || RISK_COLORS.low
  const circumference = 2 * Math.PI * 40
  const dashOffset = circumference - (score * circumference)
  const modelLabel = MODEL_LABELS[model_type] || model_type

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
            <span className="text-2xl font-bold" style={{ color: c.ring }}>{Math.round(score * 100)}</span>
            <span className="text-[10px] text-[#4b5563] uppercase tracking-[0.2em] font-mono">score</span>
          </div>
        </div>

        {/* Details */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-lg font-bold uppercase tracking-wide" style={{ color: c.ring }}>
              {level}
            </span>
            <span className="text-xs text-[#4b5563]">{modelLabel}</span>
          </div>
          <div className="text-xs text-[#9ca3af] mb-3 font-mono">
            {model_probability !== null && model_probability !== undefined
              ? `model ${pct(model_probability)} · findings ${pct(static_score)}`
              : `findings ${pct(static_score)}`}
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

      {attributions && attributions.length > 0 && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="text-[10px] text-[#4b5563] uppercase tracking-[0.2em] font-mono mb-2">
            Model attributions (vs. typical change)
          </p>
          <ul className="space-y-1">
            {attributions.slice(0, 5).map((a) => (
              <li key={a.feature} className="flex items-center justify-between text-xs">
                <span className="text-[#9ca3af]">
                  {a.label} <span className="text-[#4b5563] font-mono">= {formatValue(a.value)}</span>
                </span>
                <span className="font-mono" style={{ color: a.contribution > 0 ? '#DC2626' : '#22c55e' }}>
                  {a.contribution > 0 ? '+' : ''}{pct(a.contribution)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings && warnings.length > 0 && (
        <p className="mt-3 text-[11px] text-[#4b5563]">{warnings[0]}</p>
      )}
    </div>
  )
}
