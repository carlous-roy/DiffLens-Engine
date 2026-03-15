

const API_BASE = '/api/v1';

async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

/** Submit a diff (or raw code) for analysis. */
export async function analyzeDiff(diff, options = {}) {
  return apiFetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      diff,
      enable_ml: options.enableML !== false,
      enable_smart_review: options.enableSmartReview || false,
    }),
  });
}

/** Check backend + DB + LLM health. */
export async function fetchHealth() {
  return apiFetch(`${API_BASE}/health`);
}

/** Get ML feature availability and LLM connection info. */
export async function fetchMLStatus() {
  return apiFetch(`${API_BASE}/ml/status`);
}

/** List recent analysis runs (newest first). */
export async function fetchRuns(limit = 20) {
  return apiFetch(`${API_BASE}/runs?limit=${limit}`);
}

/** Get full details of a specific run (findings, metadata). */
export async function fetchRun(runId) {
  return apiFetch(`${API_BASE}/runs/${runId}`);
}

/** Check GitHub token validity and feature config. */
export async function fetchGitHubStatus() {
  return apiFetch(`${API_BASE}/github/status`);
}

/** List GitHub PRs that have been analyzed. */
export async function fetchGitHubPRs(limit = 20, repo = '') {
  const params = new URLSearchParams({ limit });
  if (repo) params.set('repo', repo);
  return apiFetch(`${API_BASE}/github/prs?${params}`);
}

/** Manually trigger analysis of a specific PR. */
export async function triggerPRAnalysis(owner, repo, number, token = '') {
  return apiFetch(`${API_BASE}/github/analyze-pr`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner, repo, number, token: token || undefined }),
  });
}
