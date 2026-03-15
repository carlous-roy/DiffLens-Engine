
import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2, Clock, FileCode, ExternalLink, GitPullRequest } from 'lucide-react'
import { fetchRun } from '../api'
import SeverityBadge from '../components/Badges'

export default function RunDetailPage() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchRun(runId)
      .then(setRun)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [runId])

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 size={24} className="animate-spin text-[#4b5563]" /></div>
  }

  if (error) {
    return (
      <div className="card p-12 text-center animate-fade-in">
        <p className="text-[#DC2626] mb-4">{error}</p>
        <button onClick={() => navigate('/history')} className="text-sm text-[#9ca3af] hover:text-white bg-transparent border-none cursor-pointer font-sans">← Back to History</button>
      </div>
    )
  }

  const formatDate = (iso) => iso ? new Date(iso).toLocaleString() : '—'

  /* Group findings by file for a code-review-like layout */
  const byFile = {}
  ;(run.findings || []).forEach((f) => {
    const key = f.file_path || 'unknown'
    if (!byFile[key]) byFile[key] = []
    byFile[key].push(f)
  })

  /* Check if this is a GitHub-sourced run */
  const isGitHub = run.source === 'github'

  return (
    <div className="animate-fade-in space-y-6">
      {/* Back + header */}
      <div>
        <button onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-xs text-[#4b5563] hover:text-white mb-4 transition-colors bg-transparent border-none cursor-pointer font-sans">
          <ArrowLeft size={14} /> Back
        </button>

        <div className="flex items-center justify-between">
          <div>
            <p className="section-label">Run Details</p>
            <h2 className="font-extrabold text-3xl tracking-tight">
              Run <span className="font-mono gradient-text">{runId.slice(0, 8)}</span>
            </h2>
            <div className="flex items-center gap-4 mt-2 text-xs text-[#4b5563]">
              <span className="flex items-center gap-1.5"><Clock size={12} />{formatDate(run.created_at)}</span>
              <span className={`px-2 py-0.5 rounded-full border ${
                isGitHub ? 'bg-[rgba(29,78,216,0.08)] text-[#60a5fa] border-[rgba(29,78,216,0.15)]'
                : 'bg-surface-raised text-[#4b5563] border-border'
              }`}>{run.source}</span>
              <span>{run.status}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="card px-4 py-2 text-sm font-bold text-[#e4e4e7]">
              {run.findings?.length || 0} findings
            </span>
          </div>
        </div>
      </div>

      {/* Severity summary row */}
      {run.summary && (
        <div className="grid grid-cols-4 gap-3">
          {Object.entries(run.summary.by_severity || {}).map(([sev, count]) => {
            const colors = { critical: '#DC2626', error: '#EA580C', warning: '#F59E0B', info: '#1D4ED8' }
            return (
              <div key={sev} className="card p-3 text-center">
                <div className="text-lg font-bold" style={{ color: colors[sev] || '#9ca3af' }}>{count}</div>
                <div className="text-[10px] text-[#4b5563] uppercase tracking-[0.15em] font-mono">{sev}</div>
              </div>
            )
          })}
        </div>
      )}

      {/* Findings grouped by file */}
      {Object.entries(byFile).map(([file, findings]) => (
        <div key={file} className="card overflow-hidden">
          <div className="px-5 py-3 bg-surface-raised border-b border-border flex items-center gap-2">
            <FileCode size={14} className="text-[#4b5563]" />
            <span className="font-mono text-sm text-[#e4e4e7]">{file}</span>
            <span className="text-xs text-[#4b5563] ml-auto">{findings.length} findings</span>
          </div>
          <div className="divide-y divide-border">
            {findings
              .sort((a, b) => (a.line_number || 0) - (b.line_number || 0))
              .map((f, i) => (
                <div key={i} className="px-5 py-3.5 hover:bg-surface-hover transition-colors">
                  <div className="flex items-start gap-3">
                    <span className="font-mono text-xs text-[#4b5563] w-8 text-right mt-0.5 flex-shrink-0">
                      {f.line_number || '—'}
                    </span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <SeverityBadge severity={f.severity} />
                        <span className="text-xs text-[#4b5563] font-mono">{f.analyzer}</span>
                      </div>
                      <p className="text-sm text-[#e4e4e7]">{f.message}</p>
                      {f.suggestion && (
                        <p className="text-xs text-[#22c55e] mt-1.5 opacity-70">💡 {f.suggestion}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </div>
      ))}

      {(!run.findings || run.findings.length === 0) && (
        <div className="card p-12 text-center">
          <p className="text-[#9ca3af]">No findings for this run</p>
        </div>
      )}
    </div>
  )
}
