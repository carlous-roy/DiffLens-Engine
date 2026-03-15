
import React, { useState } from 'react'
import { FileCode, ChevronDown, ChevronRight, Lightbulb } from 'lucide-react'
import SeverityBadge, { CategoryBadge } from './Badges'

function FindingCard({ finding, categorization }) {
  const [expanded, setExpanded] = useState(false)

  /* Match this finding to its auto-categorization result */
  const category = categorization?.categorized?.find(
    c => c.original_message === finding.message
  )

  return (
    <div
      className="card p-4 cursor-pointer group"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 text-[#4b5563]">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center flex-wrap gap-2 mb-1.5">
            <SeverityBadge severity={finding.severity} />
            {category && <CategoryBadge category={category.category} />}
            <span className="text-xs text-[#4b5563] font-mono">
              {finding.analyzer || finding.file_path}
            </span>
          </div>

          <p className="text-sm text-[#e4e4e7] leading-relaxed">{finding.message}</p>

          <div className="flex items-center gap-3 mt-2 text-xs text-[#4b5563]">
            <span className="flex items-center gap-1.5">
              <FileCode size={12} />
              {finding.file_path}
            </span>
            {finding.line_number && (
              <span className="font-mono">L{finding.line_number}</span>
            )}
          </div>

          {expanded && finding.suggestion && (
            <div className="mt-3 p-3 rounded-2xl animate-fade-in"
              style={{ background: 'rgba(34,197,94,0.04)', border: '1px solid rgba(34,197,94,0.1)' }}>
              <div className="flex items-center gap-1.5 text-[#22c55e] text-xs font-medium mb-1.5">
                <Lightbulb size={12} />
                Suggestion
              </div>
              <p className="text-xs text-[#9ca3af] leading-relaxed">{finding.suggestion}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function FindingsList({ findings, categorization, title }) {
  if (!findings || findings.length === 0) return null

  return (
    <div className="animate-slide-up">
      {title && (
        <h3 className="section-label">
          {title}
          <span className="ml-2 text-[#4b5563]">({findings.length})</span>
        </h3>
      )}
      <div className="space-y-2">
        {findings.map((f, i) => (
          <FindingCard key={i} finding={f} categorization={categorization} />
        ))}
      </div>
    </div>
  )
}
