import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { checkHealth } from '../api/index'
import { useBankroll, formatINR } from '../context/BankrollContext'
import AgeGate from './AgeGate'
import './Layout.css'

const NAV = [
  { to: '/app', label: 'Matches', icon: '⚡' },
  { to: '/app/model', label: 'Model', icon: '🧠' },
  { to: '/app/guide', label: 'How it works', icon: '📖' },
  { to: '/app/settings', label: 'Bankroll', icon: '💰' },
]

const BRAND = 'GAMBIT'

function Logo({ size = 30 }) {
  return (
    <span className="brand-logo" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 32 32" width={size} height={size}>
        <defs>
          <linearGradient id="g-brand" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#eaffa0" />
            <stop offset="45%" stopColor="#d4ff45" />
            <stop offset="100%" stopColor="#e8b962" />
          </linearGradient>
        </defs>
        <rect x="3" y="3" width="26" height="26" rx="7" fill="url(#g-brand)" />
        <path d="M16 8.5l2.4 5 5.1.5-3.9 3.4 1.2 5-4.8-2.7-4.8 2.7 1.2-5L9.5 14l5.1-.5z" fill="#0c0c0d" opacity="0.92" />
      </svg>
    </span>
  )
}

export default function Layout() {
  const [status, setStatus] = useState(null)
  const { bankroll } = useBankroll()
  const location = useLocation()

  useEffect(() => {
    checkHealth().then(setStatus).catch(() => setStatus({ status: 'error' }))
  }, [])

  const online = status && status.status !== 'error'

  return (
    <div className="layout">
      <AgeGate />
      {/* ── Desktop sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Logo size={34} />
          <div className="sidebar-brand-text">
            <strong className="wordmark">{BRAND}</strong>
            <small>Your betting brain · INR</small>
          </div>
        </div>

        <nav className="sidebar-nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/app'}
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
            >
              <span className="nav-icon" aria-hidden>{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-budget">
          <small>Per-match budget</small>
          <strong>{formatINR(bankroll)}</strong>
        </div>

        <div className={`sidebar-status ${online ? 'is-online' : 'is-offline'}`}>
          <span className={`dot ${online ? 'live' : 'cached'}`} />
          <span>{online ? 'WC 2026 engine active' : 'Connecting to engine…'}</span>
        </div>

        <p className="sidebar-disclaimer">18+ · Bet only what you can afford to lose.</p>
      </aside>

      {/* ── Mobile top bar ── */}
      <header className="mobile-topbar">
        <div className="sidebar-brand">
          <Logo size={26} />
          <strong className="wordmark">{BRAND}</strong>
        </div>
        <div className="mobile-budget">
          <small>Budget</small>
          <strong>{formatINR(bankroll)}</strong>
        </div>
      </header>

      <main className="main-content">
        <div className="route-view" key={location.pathname}>
          <Outlet />
        </div>
      </main>

      {/* ── Mobile bottom nav ── */}
      <nav className="bottom-nav">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/app'}
            className={({ isActive }) => (isActive ? 'bottom-item active' : 'bottom-item')}
          >
            <span className="nav-icon" aria-hidden>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
