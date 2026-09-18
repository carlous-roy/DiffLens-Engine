
import React, { useState, useEffect } from 'react'
import { Database, Brain, Check, X, Loader2, RefreshCw, Cpu, Server } from 'lucide-react'
import { fetchHealth, fetchMLStatus } from '../api'

function StatusCard({ icon: Icon, title, status, details }) {
  const isOk = status === 'healthy' || status === 'connected' || status === true || status === 'active'
  return (
    <div className="card p-6 animate-slide-up">
      <div className="flex items-center gap-3 mb-4">
        <div className={`w-10 h-10 rounded-2xl flex items-center justify-center ${
          isOk ? 'bg-[rgba(34,197,94,0.08)]' : 'bg-surface-raised'
        }`}>
          <Icon size={18} className={isOk ? 'text-[#22c55e]' : 'text-[#4b5563]'} />
        </div>
        <div>
          <h3 className="font-semibold text-sm text-[#e4e4e7]">{title}</h3>
          <div className="flex items-center gap-1.5 mt-0.5">
            {isOk ? <Check size={12} className="text-[#22c55e]" /> : <X size={12} className="text-[#4b5563]" />}
            <span className={`text-xs ${isOk ? 'text-[#22c55e]' : 'text-[#4b5563]'}`}>
              {typeof status === 'boolean' ? (status ? 'Enabled' : 'Disabled') : status}
            </span>
          </div>
        </div>
      </div>
      {details && (
        <div className="space-y-2 text-xs text-[#4b5563]">
          {Object.entries(details).map(([k, v]) => (
            <div key={k} className="flex items-center justify-between">
              <span>{k}</span>
              <span className="text-[#9ca3af] font-mono">{String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function StatusPage() {
  const [health, setHealth] = useState(null)
  const [mlStatus, setMLStatus] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    setLoading(true)
    try {
      const [h, ml] = await Promise.all([fetchHealth(), fetchMLStatus()])
      setHealth(h)
      setMLStatus(ml)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [])

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="section-label">System</p>
          <h2 className="font-extrabold text-3xl tracking-tight">System Status</h2>
          <p className="text-sm text-[#9ca3af] mt-1.5">Service health and ML feature configuration</p>
        </div>
        <button onClick={refresh} disabled={loading}
          className="flex items-center gap-2 px-4 py-2 text-xs text-[#9ca3af] hover:text-white
                   border border-border rounded-full transition-all bg-transparent font-sans disabled:opacity-50">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {loading && !health ? (
        <div className="flex items-center justify-center h-64"><Loader2 size={24} className="animate-spin text-[#4b5563]" /></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <StatusCard icon={Server} title="Application" status={health?.status || 'unknown'}
            details={{ Version: health?.version || '—', Environment: health?.environment || '—' }} />
          <StatusCard icon={Database} title="Database" status={health?.database || 'unknown'}
            details={{ Backend: health?.database_backend || '—', Status: health?.database || '—' }} />
          <StatusCard icon={Brain} title="LLM (Ollama)" status={health?.llm || 'disabled'}
            details={mlStatus?.llm ? { Provider: mlStatus.llm.provider, Model: mlStatus.llm.model, URL: mlStatus.llm.base_url, 'Models installed': mlStatus.llm.installed_models?.length || 0 } : undefined} />
          <StatusCard icon={Cpu} title="Risk Model" status={mlStatus?.risk_model?.loaded ? 'active' : 'heuristic fallback'}
            details={mlStatus?.risk_model ? {
              Type: mlStatus.risk_model.model_type,
              Version: mlStatus.risk_model.version || '—',
              'ROC-AUC (full)': mlStatus.risk_model.variants?.full?.metrics?.roc_auc ?? '—',
              'ROC-AUC (diff only)': mlStatus.risk_model.variants?.diff_only?.metrics?.roc_auc ?? '—',
            } : undefined} />
          <StatusCard icon={Cpu} title="Similarity" status={mlStatus?.similarity_index?.loaded_from_db ? 'active' : 'disabled'}
            details={mlStatus?.similarity_index ? {
              Embeddings: mlStatus.embeddings?.model || '—',
              Search: mlStatus.similarity_index.search_backend,
              Findings: mlStatus.similarity_index.findings,
              Clusters: mlStatus.similarity_index.clusters,
            } : undefined} />
          <StatusCard icon={Cpu} title="ML Features" status={Object.values(mlStatus?.features || {}).some(v => v) ? 'active' : 'disabled'}
            details={mlStatus?.features ? { 'Smart Review': mlStatus.features.smart_review ? '✓' : '✗', 'Risk Scoring': mlStatus.features.risk_scoring ? '✓' : '✗', Similarity: mlStatus.features.similarity ? '✓' : '✗', Categorization: mlStatus.features.categorization ? '✓' : '✗' } : undefined} />
        </div>
      )}
    </div>
  )
}
