
import React from 'react'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer,
} from 'recharts'

/* Color mappings aligned with portfolio design tokens */
const SEVERITY_COLORS = {
  critical: '#DC2626',
  error:    '#EA580C',
  warning:  '#F59E0B',
  info:     '#1D4ED8',
}

const CATEGORY_COLORS = {
  security:        '#DC2626',
  correctness:     '#EA580C',
  performance:     '#1D4ED8',
  maintainability: '#F59E0B',
  style:           '#22c55e',
}

/** Minimal tooltip matching the dark card style. */
function ChartTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const { name, value } = payload[0]
  return (
    <div className="bg-[#111] border border-border rounded-xl px-3 py-2 shadow-xl">
      <p className="text-xs text-[#9ca3af]">
        <span className="font-medium text-[#e4e4e7]">{name}</span>: {value}
      </p>
    </div>
  )
}

/** Severity donut chart. */
export function SeverityChart({ bySeverity }) {
  const data = Object.entries(bySeverity || {})
    .filter(([_, v]) => v > 0)
    .map(([name, value]) => ({ name, value }))

  if (data.length === 0) return null

  return (
    <div className="card p-6 animate-slide-up">
      <h3 className="section-label mb-5">By Severity</h3>
      <ResponsiveContainer width="100%" height={160}>
        <PieChart>
          <Pie
            data={data} cx="50%" cy="50%"
            innerRadius={35} outerRadius={60}
            paddingAngle={3} dataKey="value" strokeWidth={0}
          >
            {data.map((entry, i) => (
              <Cell key={i} fill={SEVERITY_COLORS[entry.name] || '#4b5563'} />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip />} />
        </PieChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap justify-center gap-3 mt-3">
        {data.map((d, i) => (
          <div key={i} className="flex items-center gap-1.5 text-xs text-[#9ca3af]">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: SEVERITY_COLORS[d.name] }} />
            {d.name} ({d.value})
          </div>
        ))}
      </div>
    </div>
  )
}

/** Category horizontal bar chart. */
export function CategoryChart({ categorization }) {
  const summary = categorization?.summary
  if (!summary) return null

  const data = Object.entries(summary)
    .filter(([_, v]) => v > 0)
    .map(([name, value]) => ({ name, value }))
  if (data.length === 0) return null

  return (
    <div className="card p-6 animate-slide-up">
      <h3 className="section-label mb-5">By Category</h3>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 10 }}>
          <XAxis type="number" hide />
          <YAxis
            type="category" dataKey="name" width={95}
            tick={{ fontSize: 11, fill: '#9ca3af' }}
            axisLine={false} tickLine={false}
          />
          <Tooltip content={<ChartTooltip />} />
          <Bar dataKey="value" radius={[0, 6, 6, 0]} barSize={18}>
            {data.map((entry, i) => (
              <Cell key={i} fill={CATEGORY_COLORS[entry.name] || '#4b5563'} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Top-level summary stat cards. */
export function SummaryStats({ summary }) {
  if (!summary) return null

  const stats = [
    { label: 'Files',    value: summary.files_analyzed,            color: '#e4e4e7' },
    { label: 'Findings', value: summary.total_findings,            color: '#EA580C' },
    { label: 'Critical', value: summary.by_severity?.critical || 0, color: '#DC2626' },
    { label: 'Errors',   value: summary.by_severity?.error || 0,    color: '#EA580C' },
    { label: 'Warnings', value: summary.by_severity?.warning || 0,  color: '#F59E0B' },
  ]

  return (
    <div className="grid grid-cols-5 gap-3 animate-slide-up">
      {stats.map((s, i) => (
        <div key={i} className="card p-4 text-center">
          <div className="text-2xl font-bold" style={{ color: s.color }}>{s.value}</div>
          <div className="text-[11px] text-[#4b5563] uppercase tracking-[0.15em] mt-1 font-mono">{s.label}</div>
        </div>
      ))}
    </div>
  )
}
