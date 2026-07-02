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
    { label: 'ROI', value: `${portfolio.roi_pct ?? 0}%`, tone: (portfolio.roi_pct ?? 0) >= 0 ? 'good' : 'warn' },
    { label: 'P/L', value: fmtUsd(portfolio.profit_usd), tone: (portfolio.profit_usd ?? 0) >= 0 ? 'good' : 'warn' },
    { label: 'Staked (USD)', value: fmtUsd(portfolio.total_staked) },
    { label: 'Win-loss', value: `${portfolio.wins ?? 0}-${portfolio.losses ?? 0}` },
    { label: 'Singles', value: portfolio.singles_count ?? 0 },
    { label: 'Parlays', value: portfolio.parlays_count ?? 0 },
    { label: 'Avg odds', value: portfolio.avg_odds ?? '—' },
  ]), [portfolio])

  const curve = portfolio.cumulative_profit || []
  const curveMax = Math.max(...curve.map((pt) => Math.abs(pt.running_profit_usd || 0)), 1)
  const marketRows = portfolio.ranked_markets || []

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
      <header className="portfolio-hero fade-up">
        <div>
          <span className="page-eyebrow">PRIVATE PORTFOLIO</span>
          <h1>Betting journal and improvement desk</h1>
          <p className="subtitle">
            Imported from your Stake session, organized into strengths, leaks, recent form, and the guardrails your
            main match screen should follow.
          </p>
          {portfolio.profile?.summary && (
            <p className="portfolio-hero-summary">{portfolio.profile.summary}</p>
          )}
        </div>
        <div className="portfolio-hero-actions">
          <button
            className="refresh-btn"
            onClick={() => runAction('connect', connectPortfolioSession)}
            disabled={busy === 'connect'}
          >
            {busy === 'connect' ? 'Opening…' : 'Open Stake login'}
          </button>
          <button
            className="refresh-btn"
            onClick={() => runAction('snapshot', refreshPortfolioSnapshot)}
            disabled={!portfolioReady || busy === 'snapshot'}
          >
            {busy === 'snapshot' ? 'Refreshing…' : 'Sync portfolio'}
          </button>
        </div>
      </header>

      {err && <div className="portfolio-alert error">{err}</div>}

      <section className="portfolio-topline fade-up">
        {summary.map((item) => (
          <div key={item.label} className={`portfolio-kpi ${item.tone || ''}`}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Performance curve</h2>
            <p className="muted">
              Your running profit over the imported sample, so you can see whether the current strategy is compounding or drifting.
            </p>
          </div>
          <span className={`portfolio-pill ${browser.have_auth_token ? 'ok' : browser.ready ? 'warn' : 'idle'}`}>
            {browser.have_auth_token ? 'Authenticated' : browser.ready ? 'Login open' : 'Connect first'}
          </span>
        </div>

        {curve.length > 1 ? (
          <div className="portfolio-curve">
            {curve.map((pt) => (
              <div key={`${pt.i}-${pt.label}`} className="curve-col">
                <div
                  className={`curve-bar ${(pt.running_profit_usd || 0) >= 0 ? 'up' : 'down'}`}
                  style={{ height: `${Math.max(10, (Math.abs(pt.running_profit_usd || 0) / curveMax) * 180)}px` }}
                  title={`${pt.label}: ${fmtUsd(pt.running_profit_usd)}`}
                />
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">Sync more than one bet to unlock the performance curve.</p>
        )}

        <div className="portfolio-note">
          <h3>Improve next</h3>
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
            <h2>Strengths and leaks</h2>
            <p className="muted">
              Which bet families are earning trust and which ones are dragging the sample.
            </p>
          </div>
        </div>

        {!marketRows.length ? (
          <p className="muted">Refresh after login to build your market breakdown.</p>
        ) : (
          <div className="portfolio-market-list">
            {marketRows.map((row) => (
              <div key={row.market} className="portfolio-market-row">
                <div className="portfolio-market-copy">
                  <strong>{row.market.replace(/_/g, ' ')}</strong>
                  <small>{row.count} bets · {row.wins}-{row.losses}</small>
                </div>
                <div className="portfolio-market-bar">
                  <div
                    className={`portfolio-market-fill ${row.profit_usd >= 0 ? 'up' : 'down'}`}
                    style={{ width: `${Math.min(100, Math.max(8, Math.abs(row.profit_usd) * 10))}%` }}
                  />
                </div>
                <strong className={row.profit_usd >= 0 ? 'green' : 'red'}>{fmtUsd(row.profit_usd)}</strong>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Learning controls</h2>
            <p className="muted">
              Keep the sensitive sync settings tucked away here instead of dominating the page.
            </p>
          </div>
          <span className={`portfolio-pill ${portfolioReady ? 'ok' : 'warn'}`}>{portfolioReady ? 'Enabled' : 'Off'}</span>
        </div>
        <div className="portfolio-controls">
          <label className="portfolio-check compact">
            <input
              type="checkbox"
              checked={Boolean(privacy.risk_acknowledged)}
              onChange={(e) => savePrivacy({ risk_acknowledged: e.target.checked })}
              disabled={busy === 'privacy'}
            />
            <span>Privacy consent accepted</span>
          </label>
          <label className="portfolio-check compact">
            <input
              type="checkbox"
              checked={Boolean(privacy.portfolio_enabled)}
              onChange={(e) => savePrivacy({ portfolio_enabled: e.target.checked })}
              disabled={busy === 'privacy'}
            />
            <span>Portfolio sync enabled</span>
          </label>
          <label className="portfolio-check compact">
            <input
              type="checkbox"
              checked={Boolean(privacy.learning_opt_in)}
              onChange={(e) => savePrivacy({ learning_opt_in: e.target.checked })}
              disabled={busy === 'privacy'}
            />
            <span>Use future results for learning</span>
          </label>
        </div>
        <div className="portfolio-inline-actions">
          <button className="refresh-btn" onClick={() => runAction('reload', fetchPortfolioState)} disabled={busy === 'reload'}>
            {busy === 'reload' ? 'Refreshing…' : 'Reload'}
          </button>
          <button className="refresh-btn" onClick={() => runAction('disconnect', disconnectPortfolioSession)} disabled={busy === 'disconnect'}>
            {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}
          </button>
        </div>
        <p className="muted">{connection.last_sync_message || portfolio.model_audit?.message}</p>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Bet journal</h2>
            <p className="muted">
              A cleaner ledger of what you actually placed, so you can review execution without noise.
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
