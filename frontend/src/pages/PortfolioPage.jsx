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

function fmtUsd(n) {
  if (n == null) return '—'
  return `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
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
    { label: 'Staked (USD)', value: fmtUsd(portfolio.total_staked) },
    { label: 'Returned (USD)', value: fmtUsd(portfolio.total_return) },
    { label: 'P/L (USD)', value: fmtUsd(portfolio.profit_usd) },
    { label: 'Win-loss', value: `${portfolio.wins ?? 0}-${portfolio.losses ?? 0}` },
    { label: 'Singles', value: portfolio.singles_count ?? 0 },
    { label: 'Parlays', value: portfolio.parlays_count ?? 0 },
    { label: 'Avg odds', value: portfolio.avg_odds ?? '—' },
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
              This uses a visible browser session you control. The app does not ask for your raw Stake password here.
            </p>
          </div>
          <span className={`portfolio-pill ${browser.ready ? 'ok' : browser.warming ? 'warn' : 'idle'}`}>
            {browser.ready ? 'Connected' : browser.warming ? 'Opening login window…' : 'Disconnected'}
          </span>
        </div>

        <div className="portfolio-actions">
          <button
            className="refresh-btn"
            onClick={() => runAction('connect', connectPortfolioSession)}
            disabled={busy === 'connect'}
          >
            {busy === 'connect' ? 'Opening…' : 'Open Stake login window'}
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

        <p className="muted">{connection.last_sync_message || 'Open Stake login to prepare a private browser session.'}</p>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Performance snapshot</h2>
            <p className="muted">
              This page refreshes from your Stake account history when privacy is enabled and the logged-in browser session is ready.
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
          <h3>What to improve</h3>
          {portfolio.insights?.length ? (
            <div className="portfolio-insights">
              {portfolio.insights.map((tip, idx) => (
                <div key={idx} className="portfolio-insight">{tip}</div>
              ))}
            </div>
          ) : (
            <p className="muted">No strong red flags yet from the imported sample.</p>
          )}
          <p className="muted">Last imported: <strong>{fmtTs(portfolio.last_imported_at)}</strong></p>
        </div>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Bet mix</h2>
            <p className="muted">
              Where your action has been going so far and which bet families are helping or hurting.
            </p>
          </div>
        </div>

        {!Object.keys(portfolio.market_breakdown || {}).length ? (
          <p className="muted">Refresh after login to build your market breakdown.</p>
        ) : (
          <div className="portfolio-market-grid">
            {Object.entries(portfolio.market_breakdown || {}).map(([family, stats]) => (
              <div key={family} className="portfolio-market-card">
                <strong>{family.replace(/_/g, ' ')}</strong>
                <div className="muted">{stats.count} bets</div>
                <div className="portfolio-market-metrics">
                  <span>W-L: <strong>{stats.wins}-{stats.losses}</strong></span>
                  <span>P/L: <strong>{fmtUsd(stats.profit_usd)}</strong></span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Model audit</h2>
            <p className="muted">
              This is where the app will compare your placed bets against what the model believed at the time.
            </p>
          </div>
          <span className={`portfolio-pill ${portfolio.model_audit?.available ? 'ok' : 'warn'}`}>
            {portfolio.model_audit?.available ? 'Ready' : 'Next layer'}
          </span>
        </div>
        <p className="muted">{portfolio.model_audit?.message}</p>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Recent imported bets</h2>
            <p className="muted">
              These are pulled from your Stake session and stored privately on this machine until you delete them.
            </p>
          </div>
          <span className={`portfolio-pill ${portfolio.bets?.length ? 'ok' : 'idle'}`}>
            {portfolio.bets?.length ? `${portfolio.bets.length} loaded` : 'No bets yet'}
          </span>
        </div>

        {!portfolio.bets?.length ? (
          <p className="muted">
            No imported bets yet. Open the Stake login window, make sure you are fully signed in, then press
            `Refresh portfolio now`.
          </p>
        ) : (
          <div className="portfolio-bets">
            {portfolio.bets.map((bet) => (
              <div key={bet.id} className={`portfolio-bet status-${bet.status || 'unknown'}`}>
                <div className="portfolio-bet-top">
                  <div>
                    <strong>{bet.fixture_name}</strong>
                    <div className="muted">{bet.league || 'Unknown league'} · {fmtTs(bet.created_at)}</div>
                  </div>
                  <div className="portfolio-bet-badges">
                    <span className="portfolio-pill idle">{bet.bet_type || 'bet'}</span>
                    <span className="portfolio-pill idle">{bet.market_family || 'other'}</span>
                    <span className={`portfolio-pill ${bet.status === 'won' ? 'ok' : bet.status === 'lost' ? 'warn' : 'idle'}`}>
                      {bet.status || 'unknown'}
                    </span>
                  </div>
                </div>

                <div className="portfolio-bet-grid">
                  <div>
                    <span>Stake</span>
                    <strong>{bet.stake} {bet.currency}</strong>
                  </div>
                  <div>
                    <span>Payout</span>
                    <strong>{bet.payout ? `${bet.payout} ${bet.currency}` : '—'}</strong>
                  </div>
                  <div>
                    <span>Odds</span>
                    <strong>{bet.combined_odds || bet.potential_multiplier || '—'}</strong>
                  </div>
                  <div>
                    <span>P/L USD</span>
                    <strong>{fmtUsd(bet.profit_usd)}</strong>
                  </div>
                </div>

                <div className="portfolio-selection-list">
                  {(bet.selections || []).map((sel, idx) => (
                    <div key={`${bet.id}-${idx}`} className="portfolio-selection">
                      <span>{sel.selection || 'Selection'}</span>
                      <small>{sel.fixture_name || bet.fixture_name} · {sel.odds || '—'}</small>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
