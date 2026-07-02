import { useEffect, useMemo, useState } from 'react'
import {
  connectPortfolioSession,
  disconnectPortfolioSession,
  fetchPortfolioState,
  refreshPortfolioSnapshot,
  updatePortfolioPrivacy,
} from '../api'
import './pages.css'

function fmtTs(ts) {
  if (!ts) return 'Never'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

export default function PortfolioPage() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')

  const load = async ({ autoRefresh = false } = {}) => {
    setErr('')
    const next = await fetchPortfolioState()
    setState(next)
    if (
      autoRefresh &&
      next?.privacy?.portfolio_enabled &&
      next?.privacy?.risk_acknowledged &&
      next?.connection?.browser?.ready
    ) {
      const refreshed = await refreshPortfolioSnapshot()
      setState(refreshed)
    }
  }

  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        const next = await fetchPortfolioState()
        if (!mounted) return
        setState(next)
        if (
          next?.privacy?.portfolio_enabled &&
          next?.privacy?.risk_acknowledged &&
          next?.connection?.browser?.ready
        ) {
          const refreshed = await refreshPortfolioSnapshot()
          if (mounted) setState(refreshed)
        }
      } catch (e) {
        if (mounted) setErr(String(e))
      } finally {
        if (mounted) setLoading(false)
      }
    })()
    return () => { mounted = false }
  }, [])

  const privacy = state?.privacy || {}
  const connection = state?.connection || {}
  const browser = connection?.browser || {}
  const portfolio = state?.portfolio || {}
  const portfolioReady = privacy.portfolio_enabled && privacy.risk_acknowledged

  const summary = useMemo(() => ([
    { label: 'Imported bets', value: portfolio.bet_count ?? 0 },
    { label: 'Settled', value: portfolio.settled_count ?? 0 },
    { label: 'Open', value: portfolio.open_count ?? 0 },
    { label: 'ROI', value: `${portfolio.roi_pct ?? 0}%` },
  ]), [portfolio])

  const savePrivacy = async (patch = {}) => {
    if (!state) return
    setBusy('privacy')
    setErr('')
    try {
      const next = await updatePortfolioPrivacy({
        portfolio_enabled: patch.portfolio_enabled ?? privacy.portfolio_enabled ?? false,
        risk_acknowledged: patch.risk_acknowledged ?? privacy.risk_acknowledged ?? false,
        learning_opt_in: patch.learning_opt_in ?? privacy.learning_opt_in ?? false,
      })
      setState(next)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy('')
    }
  }

  const runAction = async (key, fn) => {
    setBusy(key)
    setErr('')
    try {
      const next = await fn()
      setState(next)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy('')
    }
  }

  if (loading) {
    return <div className="page"><p className="muted">Loading your private portfolio controls…</p></div>
  }

  return (
    <div className="page portfolio-page">
      <header className="simple-hero fade-up">
        <span className="page-eyebrow">🔒 PRIVATE PORTFOLIO</span>
        <h1>Stake-linked portfolio</h1>
        <p className="subtitle">
          Private by default. Portfolio sync stays off until you accept the privacy warning, and your imported data
          remains hidden from other users unless you explicitly enable this device-local portfolio.
        </p>
      </header>

      {err && <div className="portfolio-alert error">{err}</div>}

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Privacy and consent</h2>
            <p className="muted">
              Imported Stake data stays saved locally even if the browser session expires. You can disconnect the
              session without deleting stored history.
            </p>
          </div>
          <span className={`portfolio-pill ${portfolioReady ? 'ok' : 'warn'}`}>
            {portfolioReady ? 'Enabled' : 'Disabled'}
          </span>
        </div>

        <label className="portfolio-check">
          <input
            type="checkbox"
            checked={Boolean(privacy.risk_acknowledged)}
            onChange={(e) => savePrivacy({ risk_acknowledged: e.target.checked })}
            disabled={busy === 'privacy'}
          />
          <span>I understand the privacy risks of importing sensitive betting history into this app.</span>
        </label>

        <label className="portfolio-check">
          <input
            type="checkbox"
            checked={Boolean(privacy.portfolio_enabled)}
            onChange={(e) => savePrivacy({ portfolio_enabled: e.target.checked })}
            disabled={busy === 'privacy'}
          />
          <span>Enable my private portfolio on this app.</span>
        </label>

        <label className="portfolio-check">
          <input
            type="checkbox"
            checked={Boolean(privacy.learning_opt_in)}
            onChange={(e) => savePrivacy({ learning_opt_in: e.target.checked })}
            disabled={busy === 'privacy'}
          />
          <span>Allow future model-learning features to use my bet results after I opt in.</span>
        </label>

        <p className="muted">
          Consent accepted: <strong>{fmtTs(privacy.consent_accepted_at)}</strong>
        </p>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Stake session</h2>
            <p className="muted">
              This uses a browser session you control. The app does not ask for your raw Stake password here.
            </p>
          </div>
          <span className={`portfolio-pill ${browser.ready ? 'ok' : browser.warming ? 'warn' : 'idle'}`}>
            {browser.ready ? 'Connected' : browser.warming ? 'Opening browser…' : 'Disconnected'}
          </span>
        </div>

        <div className="portfolio-actions">
          <button
            className="refresh-btn"
            onClick={() => runAction('connect', connectPortfolioSession)}
            disabled={busy === 'connect'}
          >
            {busy === 'connect' ? 'Connecting…' : 'Connect Stake session'}
          </button>
          <button
            className="refresh-btn"
            onClick={() => runAction('disconnect', disconnectPortfolioSession)}
            disabled={busy === 'disconnect'}
          >
            {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect session'}
          </button>
          <button
            className="refresh-btn"
            onClick={() => runAction('reload', fetchPortfolioState)}
            disabled={busy === 'reload'}
          >
            {busy === 'reload' ? 'Refreshing…' : 'Reload status'}
          </button>
        </div>

        <div className="portfolio-grid compact">
          <div className="portfolio-stat">
            <span>Status</span>
            <strong>{connection.status || 'disconnected'}</strong>
          </div>
          <div className="portfolio-stat">
            <span>Browser ready</span>
            <strong>{browser.ready ? 'Yes' : 'No'}</strong>
          </div>
          <div className="portfolio-stat">
            <span>Last connected</span>
            <strong>{fmtTs(connection.last_connected_at)}</strong>
          </div>
          <div className="portfolio-stat">
            <span>Last sync</span>
            <strong>{fmtTs(connection.last_sync_at)}</strong>
          </div>
        </div>

        <p className="muted">{connection.last_sync_message || 'Connect Stake to prepare a private browser session.'}</p>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Portfolio snapshot</h2>
            <p className="muted">
              This page auto-refreshes on open when privacy is enabled and the Stake browser session is ready.
            </p>
          </div>
          <button
            className="refresh-btn"
            onClick={() => runAction('snapshot', refreshPortfolioSnapshot)}
            disabled={!portfolioReady || busy === 'snapshot'}
          >
            {busy === 'snapshot' ? 'Refreshing…' : 'Refresh portfolio now'}
          </button>
        </div>

        <div className="portfolio-grid">
          {summary.map((item) => (
            <div key={item.label} className="portfolio-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>

        <div className="portfolio-note">
          <h3>Current build status</h3>
          <p>
            The private consent model, local storage, and browser-session refresh path are now wired in. The next step
            is importing your actual Stake account history into this portfolio snapshot and grading those bets against
            the model and original prices.
          </p>
          <p className="muted">Last imported: <strong>{fmtTs(portfolio.last_imported_at)}</strong></p>
        </div>
      </section>
    </div>
  )
}
