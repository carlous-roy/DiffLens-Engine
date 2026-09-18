
import React, { useState } from 'react'
import { Loader2, Sparkles, Code2 } from 'lucide-react'
import { analyzeDiff } from '../api'
import { SummaryStats, SeverityChart, CategoryChart } from '../components/Charts'
import RiskGauge from '../components/RiskGauge'
import FindingsList from '../components/FindingsList'

const SAMPLE_DIFF = `diff --git a/utils/helpers.py b/utils/helpers.py
new file mode 100644
--- /dev/null
+++ b/utils/helpers.py
@@ -0,0 +1,20 @@
+from os import *
+
+class dataProcessor:
+    def ProcessData(self, data, cache={}):
+        if data is None:
+            return []
+        if data == None:
+            pass
+        try:
+            result = eval(data)
+        except:
+            pass
+        return result
+
+    # TODO: implement logging
+    def helper(self):
+        global SHARED_STATE
+        SHARED_STATE = True
+        return SHARED_STATE
`

export default function AnalyzePage() {
  const [diff, setDiff] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleAnalyze = async () => {
    if (!diff.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await analyzeDiff(diff)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const loadSample = () => {
    setDiff(SAMPLE_DIFF)
    setResult(null)
    setError(null)
  }

  /* Flatten and sort all findings by severity for the combined list */
  const allFindings = [
    ...(result?.complexity_findings || []).map(f => ({ ...f, analyzer: 'complexity' })),
    ...(result?.naming_findings || []).map(f => ({ ...f, analyzer: 'naming' })),
    ...(result?.bug_risk_findings || []).map(f => ({ ...f, analyzer: 'bug_risk' })),
  ].sort((a, b) => {
    const order = { critical: 0, error: 1, warning: 2, info: 3 }
    return (order[a.severity] ?? 4) - (order[b.severity] ?? 4)
  })

  return (
    <div className="space-y-8">
      {/* ─── Input section ─── */}
      <div className="animate-fade-in">
        <div className="flex items-center justify-between mb-5">
          <div>
            <p className="section-label">Analyze</p>
            <h2 className="font-extrabold text-3xl tracking-tight">Analyze Code</h2>
            <p className="text-sm text-[#9ca3af] mt-1.5">
              Paste a unified diff or raw Python or Java code
            </p>
          </div>
          <button
            onClick={loadSample}
            className="flex items-center gap-2 px-4 py-2 text-xs text-[#9ca3af] hover:text-white
                     border border-border hover:border-border-hover rounded-full transition-all
                     hover:-translate-y-0.5 bg-transparent font-sans"
          >
            <Code2 size={14} />
            Load Sample
          </button>
        </div>

        <div className="card overflow-hidden">
          <textarea
            value={diff}
            onChange={(e) => setDiff(e.target.value)}
            placeholder="Paste code or a unified diff here..."
            className="w-full h-56 bg-transparent p-5 font-mono text-sm text-[#e4e4e7]
                     placeholder-[#4b5563] resize-none focus:outline-none leading-relaxed"
            spellCheck={false}
          />
          <div className="border-t border-border px-5 py-3 flex items-center justify-between">
            <span className="text-xs text-[#4b5563] font-mono">
              {diff ? `${diff.split('\n').length} lines` : 'No input'}
            </span>
            <button
              onClick={handleAnalyze}
              disabled={loading || !diff.trim()}
              className="flex items-center gap-2 px-5 py-2.5 rounded-full font-medium text-sm
                       text-white disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all hover:-translate-y-0.5 font-sans"
              style={{
                background: 'linear-gradient(135deg, #DC2626, #EA580C)',
                boxShadow: '0 4px 24px rgba(220,38,38,0.2)',
              }}
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  Analyze
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 p-4 rounded-2xl text-sm text-[#DC2626] animate-fade-in"
            style={{ background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.15)' }}>
            {error}
          </div>
        )}
      </div>

      {/* ─── Results ─── */}
      {result && (
        <div className="space-y-6">
          <div className="flex items-center gap-3 text-xs text-[#4b5563] animate-fade-in">
            <span className="font-mono bg-surface-raised px-3 py-1.5 rounded-full border border-border">
              Run {result.run_id?.slice(0, 8)}...
            </span>
            <span>{result.summary?.total_findings || 0} findings across {result.summary?.files_analyzed || 0} file(s)</span>
          </div>

          <SummaryStats summary={result.summary} />

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <RiskGauge riskScore={result.risk_score} />
            <SeverityChart bySeverity={result.summary?.by_severity} />
            <CategoryChart categorization={result.categorization} />
          </div>

          <FindingsList
            findings={allFindings}
            categorization={result.categorization}
            title="All Findings"
          />
        </div>
      )}
    </div>
  )
}
