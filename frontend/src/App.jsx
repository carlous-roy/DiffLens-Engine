
import React from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { Search, History, Activity, GitPullRequest } from 'lucide-react'
import AnalyzePage from './pages/AnalyzePage'
import HistoryPage from './pages/HistoryPage'
import RunDetailPage from './pages/RunDetailPage'
import StatusPage from './pages/StatusPage'
import GitHubPage from './pages/GitHubPage'

/** Navigation pill — active state uses subtle white bg like portfolio nav. */
function NavItem({ to, icon: Icon, children }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-1.5 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${
          isActive
            ? 'bg-white/[0.06] text-white'
            : 'text-[#9ca3af] hover:text-white'
        }`
      }
    >
      <Icon size={15} />
      <span>{children}</span>
    </NavLink>
  )
}

/** DiffLens logo mark — gradient circle with monogram. */
function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold"
        style={{ background: 'linear-gradient(135deg, #DC2626, #EA580C)' }}
      >
        D
      </div>
      <span className="font-semibold text-[17px] tracking-tight">
        Diff<span className="gradient-text">Lens</span>
      </span>
      <span className="font-mono text-[10px] text-[#4b5563] ml-0.5">v1.0</span>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col noise-overlay relative">
        {/* ─── Fixed navbar (portfolio style: blur + border-b) ─── */}
        <nav className="fixed top-0 left-0 right-0 z-[100] h-16 flex items-center justify-between px-6 bg-[#08080c]/85 backdrop-blur-2xl border-b border-border">
          <Logo />
          <div className="flex items-center gap-1">
            <NavItem to="/" icon={Search}>Analyze</NavItem>
            <NavItem to="/github" icon={GitPullRequest}>GitHub</NavItem>
            <NavItem to="/history" icon={History}>History</NavItem>
            <NavItem to="/status" icon={Activity}>Status</NavItem>
          </div>
        </nav>

        {/* ─── Main content (offset for fixed nav) ─── */}
        <main className="flex-1 max-w-[1100px] mx-auto w-full px-6 pt-24 pb-12">
          <Routes>
            <Route path="/" element={<AnalyzePage />} />
            <Route path="/github" element={<GitHubPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/runs/:runId" element={<RunDetailPage />} />
            <Route path="/status" element={<StatusPage />} />
          </Routes>
        </main>

        {/* ─── Footer ─── */}
        <footer className="border-t border-border py-5">
          <div className="max-w-[1100px] mx-auto px-6 flex items-center justify-between text-xs text-[#4b5563]">
            <span>DiffLens · ML-Powered Code Review</span>
            <span>GitHub Integration</span>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  )
}
