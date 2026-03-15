
import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Clock, ChevronRight, AlertTriangle, FileCode, Loader2, Filter } from 'lucide-react'
import { fetchRuns } from '../api'

export default function HistoryPage() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const navigate = useNavigate()

  useEffect(() => {
    fetchRuns(50)
      .then(setRuns)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const formatDate = (iso) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  }

  const filtered = filter === 'all' ? runs : runs.filter(r => r.source === filter)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-[#4b5563]" />
      </div>
    )
  }

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="section-label">History</p>
          <h2 className="font-extrabold text-3xl tracking-tight">Analysis History</h2>
          <p className="text-sm text-[#9ca3af] mt-1.5">Past code review runs and their results</p>
        </div>
        {/* Source filter */}
        <div className="flex items-center gap-1">
          {['all', 'api', 'github'].map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all font-sans border-none cursor-pointer ${
                filter === f ? 'bg-white/[0.06] text-white' : 'text-[#4b5563] hover:text-[#9ca3af] bg-transparent'
              }`}>{f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}</button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="card p-12 text-center">
          <Clock size={32} className="mx-auto text-[#4b5563] mb-3" />
          <p className="text-[#9ca3af]">No analysis runs yet</p>
          <p className="text-xs text-[#4b5563] mt-1">Submit a diff on the Analyze page to get started</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((run) => {
            const total = run.summary?.total_findings || 0
            const critical = run.summary?.by_severity?.critical || 0
            const errors = run.summary?.by_severity?.error || 0

            return (
              <div key={run.id} onClick={() => navigate(`/runs/${run.id}`)}
                className="card p-4 flex items-center gap-4 cursor-pointer group">
                <div className="w-10 h-10 rounded-2xl bg-surface-raised flex items-center justify-center flex-shrink-0">
                  <FileCode size={18} className="text-[#4b5563]" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#e4e4e7] font-mono">{run.id.slice(0, 8)}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${
                      run.source === 'github'
                        ? 'bg-[rgba(29,78,216,0.08)] text-[#60a5fa] border-[rgba(29,78,216,0.15)]'
                        : 'bg-surface-raised text-[#4b5563] border-border'
                    }`}>{run.source}</span>
                    {critical > 0 && <span className="badge-critical"><AlertTriangle size={10} className="mr-1" />{critical} critical</span>}
                  </div>
                  <div className="flex items-center gap-4 mt-1 text-xs text-[#4b5563]">
                    <span>{run.summary?.files_analyzed || 0} files</span>
                    <span>{total} findings</span>
                    {errors > 0 && <span className="text-[#EA580C]">{errors} errors</span>}
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-xs text-[#4b5563]">{formatDate(run.created_at)}</span>
                  <ChevronRight size={16} className="text-[#4b5563] group-hover:text-[#DC2626] transition-colors" />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
