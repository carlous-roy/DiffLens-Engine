
import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { GitPullRequest, ExternalLink, RefreshCw, AlertCircle, CheckCircle2, Clock, Play } from 'lucide-react'
import { fetchGitHubPRs, fetchGitHubStatus, triggerPRAnalysis } from '../api'

function StatusDot({ active }) {
  return <span className={`inline-block w-2 h-2 rounded-full ${active ? 'bg-[#22c55e]' : 'bg-[#4b5563]'}`} />
}

function FindingsBadge({ summary }) {
  if (!summary) return <span className="text-[#4b5563] text-xs">—</span>
  const total = summary.total_findings || 0
  const sev = summary.by_severity || {}
  const hasErrors = (sev.error || 0) + (sev.critical || 0) > 0
  const cls = hasErrors
    ? 'bg-[rgba(220,38,38,0.08)] text-[#DC2626] border-[rgba(220,38,38,0.15)]'
    : total > 0
      ? 'bg-[rgba(245,158,11,0.08)] text-[#F59E0B] border-[rgba(245,158,11,0.15)]'
      : 'bg-[rgba(34,197,94,0.08)] text-[#22c55e] border-[rgba(34,197,94,0.15)]'
  return <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border ${cls}`}>{total} findings</span>
}

export default function GitHubPage() {
  const [prs, setPrs] = useState([])
  const [ghStatus, setGhStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showTrigger, setShowTrigger] = useState(false)
  const [triggerForm, setTriggerForm] = useState({ owner: '', repo: '', number: '' })
  const [apiKey, setApiKey] = useState(() => sessionStorage.getItem('difflens-api-key') || '')
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [triggerResult, setTriggerResult] = useState(null)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [prData, statusData] = await Promise.all([fetchGitHubPRs(30), fetchGitHubStatus()])
      setPrs(prData)
      setGhStatus(statusData)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [])

  const handleTrigger = async (e) => {
    e.preventDefault()
    setTriggerLoading(true)
    setTriggerResult(null)
    try {
      sessionStorage.setItem('difflens-api-key', apiKey)
      const result = await triggerPRAnalysis(
        triggerForm.owner, triggerForm.repo, parseInt(triggerForm.number), apiKey,
      )
      setTriggerResult({ success: true, message: result.message })
      setTimeout(loadData, 3000)
    } catch (err) { setTriggerResult({ success: false, message: err.message }) }
    finally { setTriggerLoading(false) }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="section-label">Integrations</p>
          <h2 className="font-extrabold text-3xl tracking-tight flex items-center gap-3">
            GitHub Integration
          </h2>
          <p className="text-sm text-[#9ca3af] mt-1.5">Pull requests analyzed via webhooks</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowTrigger(!showTrigger)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-medium
              border border-border-hover text-[#DC2626] hover:-translate-y-0.5 transition-all bg-transparent font-sans">
            <Play size={12} /> Analyze PR
          </button>
          <button onClick={loadData} disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-medium
              bg-transparent text-[#9ca3af] border border-border hover:text-white transition-all disabled:opacity-50 font-sans">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
      </div>

      {/* Status card */}
      {ghStatus && (
        <div className="card p-5">
          <h3 className="text-sm font-medium text-[#e4e4e7] mb-3">Integration Status</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
            <div className="flex items-center gap-2">
              <StatusDot active={ghStatus.configured} />
              <span className="text-[#4b5563]">Token:</span>
              <span className={ghStatus.configured ? 'text-[#22c55e]' : 'text-[#4b5563]'}>
                {ghStatus.configured ? (ghStatus.authenticated_as ? `@${ghStatus.authenticated_as}` : 'configured') : 'not set'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot active={ghStatus.webhook_secret_set} />
              <span className="text-[#4b5563]">Webhook:</span>
              <span className={ghStatus.webhook_secret_set ? 'text-[#22c55e]' : 'text-[#F59E0B]'}>
                {ghStatus.webhook_secret_set ? 'secured' : 'not set'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot active={ghStatus.features?.post_review} />
              <span className="text-[#4b5563]">Reviews:</span>
              <span className="text-[#9ca3af]">{ghStatus.features?.post_review ? 'on' : 'off'}</span>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot active={ghStatus.features?.use_checks_api} />
              <span className="text-[#4b5563]">Checks API:</span>
              <span className="text-[#9ca3af]">{ghStatus.features?.use_checks_api ? 'on' : 'off'}</span>
            </div>
          </div>
        </div>
      )}

      {/* Manual trigger form */}
      {showTrigger && (
        <div className="card p-5" style={{ borderColor: 'rgba(220,38,38,0.15)' }}>
          <h3 className="text-sm font-medium text-[#DC2626] mb-3">Manually Analyze a PR</h3>
          <p className="text-xs text-[#4b5563] mb-3">
            Uses the server&apos;s GitHub token, so it needs the server&apos;s API key.
          </p>
          <div className="mb-3">
            <label className="block text-xs text-[#4b5563] mb-1">API key</label>
            <input type="password" value={apiKey} autoComplete="off"
              onChange={e => setApiKey(e.target.value)}
              placeholder="X-API-Key" required
              className="w-full bg-surface-raised border border-border rounded-xl px-3 py-2
                text-sm text-[#e4e4e7] placeholder-[#4b5563] font-sans" />
          </div>
          <div className="flex items-end gap-3">
            {['owner', 'repo'].map(field => (
              <div key={field} className="flex-1">
                <label className="block text-xs text-[#4b5563] mb-1 capitalize">{field}</label>
                <input type="text" value={triggerForm[field]}
                  onChange={e => setTriggerForm(f => ({ ...f, [field]: e.target.value }))}
                  placeholder={field === 'owner' ? 'octocat' : 'hello-world'} required
                  className="w-full bg-surface-raised border border-border rounded-xl px-3 py-2
                    text-sm text-[#e4e4e7] placeholder-[#4b5563] font-sans" />
              </div>
            ))}
            <div className="w-24">
              <label className="block text-xs text-[#4b5563] mb-1">PR #</label>
              <input type="number" value={triggerForm.number}
                onChange={e => setTriggerForm(f => ({ ...f, number: e.target.value }))}
                placeholder="42" required min="1"
                className="w-full bg-surface-raised border border-border rounded-xl px-3 py-2
                  text-sm text-[#e4e4e7] placeholder-[#4b5563] font-sans" />
            </div>
            <button onClick={handleTrigger} disabled={triggerLoading}
              className="px-5 py-2 rounded-full text-sm font-medium text-white disabled:opacity-50 font-sans"
              style={{ background: 'linear-gradient(135deg, #DC2626, #EA580C)' }}>
              {triggerLoading ? '...' : 'Go'}
            </button>
          </div>
          {triggerResult && (
            <div className={`mt-3 text-xs flex items-center gap-1.5 ${triggerResult.success ? 'text-[#22c55e]' : 'text-[#DC2626]'}`}>
              {triggerResult.success ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
              {triggerResult.message}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-2xl p-4 text-sm text-[#DC2626] flex items-center gap-2"
          style={{ background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.15)' }}>
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && prs.length === 0 && !error && (
        <div className="text-center py-20 text-[#4b5563]">
          <GitPullRequest size={40} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">No pull requests analyzed yet.</p>
          <p className="text-xs mt-1">Configure a webhook pointing to <code className="text-[#9ca3af] font-mono">/api/v1/github/webhook</code></p>
        </div>
      )}

      {/* PR table */}
      {prs.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-[#4b5563] uppercase tracking-[0.1em] font-mono">
                <th className="text-left px-5 py-3 font-medium">Pull Request</th>
                <th className="text-left px-5 py-3 font-medium">Action</th>
                <th className="text-left px-5 py-3 font-medium">Findings</th>
                <th className="text-left px-5 py-3 font-medium">SHA</th>
                <th className="text-left px-5 py-3 font-medium">Analyzed</th>
                <th className="text-right px-5 py-3 font-medium">Links</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {prs.map(pr => (
                <tr key={pr.id} className="hover:bg-surface-hover transition-colors">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <GitPullRequest size={14} className="text-[#22c55e] flex-shrink-0" />
                      <span className="text-[#e4e4e7]">{pr.owner}/{pr.repo}<span className="text-[#DC2626] font-medium ml-1">#{pr.pr_number}</span></span>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${
                      pr.action === 'opened' ? 'bg-[rgba(34,197,94,0.08)] text-[#22c55e] border-[rgba(34,197,94,0.15)]'
                      : pr.action === 'synchronize' ? 'bg-[rgba(29,78,216,0.08)] text-[#60a5fa] border-[rgba(29,78,216,0.15)]'
                      : 'bg-surface-raised text-[#9ca3af] border-border'
                    }`}>{pr.action}</span>
                  </td>
                  <td className="px-5 py-3"><FindingsBadge summary={pr.summary} /></td>
                  <td className="px-5 py-3"><code className="text-xs text-[#4b5563] font-mono">{pr.head_sha?.slice(0, 7)}</code></td>
                  <td className="px-5 py-3">
                    <span className="text-xs text-[#4b5563] flex items-center gap-1">
                      <Clock size={11} />
                      {pr.created_at ? new Date(pr.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <Link to={`/runs/${pr.run_id}`} className="text-xs text-[#DC2626] hover:underline">Details</Link>
                      {pr.pr_url && <a href={pr.pr_url} target="_blank" rel="noopener noreferrer" className="text-[#4b5563] hover:text-[#e4e4e7] transition-colors"><ExternalLink size={13} /></a>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
