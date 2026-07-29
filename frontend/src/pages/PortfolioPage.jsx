import { useEffect, useMemo, useState } from 'react'
import {
  connectPortfolioSession,
  disconnectPortfolioSession,
  fetchErrorMessage,
  fetchPortfolioState,
  checkHealth,
  refreshPortfolioSnapshot,
  updatePortfolioPrivacy,
} from '../api'
import PortfolioCurve from '../components/PortfolioCurve'
import { useEntryReady } from '../components/EntryScreen'
import './pages.css'

function fmtTs(ts) {
  if (!ts) return 'Never'
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

function fmtMoney(n, currency = 'USD') {
  if (n == null) return 'n/a'
  const symbol = currency === 'INR' ? '₹' : currency === 'USD' ? '$' : `${currency} `
  return `${symbol}${Math.round(Number(n)).toLocaleString(undefined)}`
}

export default function PortfolioPage() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [cloudStake, setCloudStake] = useState(false)
  const [stakeLive, setStakeLive] = useState(false)
  useEntryReady(!loading)

  const load = async ({ autoRefresh = false } = {}) => {
    setErr('')
    const next = await fetchPortfolioState()
    setState(next)
    if (
      autoRefresh &&
      next?.privacy?.portfolio_enabled &&
      next?.privacy?.risk_acknowledged &&
      (next?.connection?.status === 'authenticated' || next?.connection?.browser?.have_auth_token)
    ) {
      const refreshed = await refreshPortfolioSnapshot()
      setState(refreshed)
    }
  }

  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        const [next, health] = await Promise.all([
          fetchPortfolioState(),
          checkHealth().catch(() => null),
        ])
        if (!mounted) return
        setState(next)
        const live = Boolean(health?.stake_live || health?.stake_remote)
        setStakeLive(live)
        // Host has no live browser path — journal still works from last sync.
        setCloudStake(health?.stake_use_browser === false && !health?.stake_remote)
        if (
          next?.privacy?.portfolio_enabled &&
          next?.privacy?.risk_acknowledged &&
          (next?.connection?.status === 'authenticated'
            || next?.connection?.browser?.have_auth_token)
          && live
        ) {
          const refreshed = await refreshPortfolioSnapshot()
          if (mounted) setState(refreshed)
        }
      } catch (e) {
        if (mounted) setErr(fetchErrorMessage(e, 'Could not load portfolio state.'))
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
  const syncStatus = connection.last_sync_status || 'never'
  const betCount = Array.isArray(portfolio.bets) ? portfolio.bets.length : 0
  const hasJournal = betCount > 0 || syncStatus === 'imported' || connection.status === 'relay'
  const syncMessage = connection.last_sync_message || ''
  const loginUrl = connection.login_url || browser.login_url || ''
  const canLiveConnect = stakeLive || !cloudStake
  const stakeLoggedIn = connection.status === 'authenticated'
    || connection.status === 'relay'
    || Boolean(browser.have_auth_token)
  const canSync = portfolioReady && canLiveConnect && (stakeLoggedIn || browser.ready)
  const needsSignIn = ['awaiting_login', 'auth_required'].includes(connection.status)
    || syncStatus === 'auth_required'
  const softSetup = !hasJournal && (
    ['setup', 'cloud'].includes(connection.status) || (cloudStake && !stakeLive)
  )
  const showAttention = needsSignIn && !hasJournal
  const money = (n) => fmtMoney(n, portfolio.display_currency)

  const summary = useMemo(() => ([
    { label: 'ROI', value: `${portfolio.roi_pct ?? 0}%`, tone: (portfolio.roi_pct ?? 0) >= 0 ? 'good' : 'warn' },
    { label: 'P/L', value: money(portfolio.profit_value), tone: (portfolio.profit_value ?? 0) >= 0 ? 'good' : 'warn' },
    { label: 'Staked', value: money(portfolio.total_staked) },
    { label: 'Win-loss-push', value: `${portfolio.wins ?? 0}-${portfolio.losses ?? 0}-${portfolio.pushes ?? 0}` },
    { label: 'Singles', value: portfolio.singles_count ?? 0 },
    { label: 'Parlays', value: portfolio.parlays_count ?? 0 },
    { label: 'Avg odds', value: portfolio.avg_odds ?? 'n/a' },
  ]), [portfolio])

  const curve = portfolio.cumulative_profit || []
  const marketRows = portfolio.ranked_markets || []
  const audit = portfolio.model_audit || {}
  const overview = portfolio.overview || {}
  const resultSummary = [
    { label: 'Wins', value: portfolio.wins ?? 0, cls: 'good' },
    { label: 'Losses', value: portfolio.losses ?? 0, cls: 'bad' },
    { label: 'Pushes', value: portfolio.pushes ?? 0, cls: 'push' },
    { label: 'Cashouts', value: portfolio.cashouts ?? 0, cls: 'cashout' },
  ]
  const settledTotal = Math.max(1, (portfolio.wins ?? 0) + (portfolio.losses ?? 0) + (portfolio.pushes ?? 0) + (portfolio.cashouts ?? 0))

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
      setErr(fetchErrorMessage(e, 'Portfolio privacy update failed.'))
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
      const status = next?.connection?.last_sync_status
      const message = next?.connection?.last_sync_message
      if (key === 'snapshot' && status && status !== 'imported' && message) {
        setErr(message)
      }
    } catch (e) {
      setErr(fetchErrorMessage(e, 'Portfolio action failed.'))
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
          <span className="page-eyebrow">PORTFOLIO</span>
          <h1>Betting journal</h1>
          <p className="subtitle">
            Imported from your Stake session. Strengths, leaks, and recent form.
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
            title="Connect your Stake account"
          >
            {busy === 'connect' ? 'Connecting…' : 'Connect Stake'}
          </button>
          <button
            className="refresh-btn"
            onClick={() => runAction('snapshot', refreshPortfolioSnapshot)}
            disabled={!canSync || busy === 'snapshot'}
            title={
              !portfolioReady
                ? 'Enable portfolio sync and accept the privacy note first'
                : !canLiveConnect
                  ? 'Sync will be available once Stake connect is ready'
                  : !stakeLoggedIn && !browser.ready
                    ? 'Connect Stake first'
                    : 'Refresh your Stake bet history'
            }
          >
            {busy === 'snapshot' ? 'Refreshing…' : 'Sync'}
          </button>
        </div>
      </header>

      {hasJournal && (
        <div className="portfolio-alert">
          {syncMessage || `Journal ready${betCount ? ` · ${betCount} bets` : ''}.`}
          {connection.last_sync_at ? ` Updated ${fmtTs(connection.last_sync_at)}.` : ''}
        </div>
      )}

      {softSetup && !err && (
        <div className="portfolio-alert">
          Connect Stake once to import your betting journal. Enable private sync below, then tap Connect Stake.
          {canLiveConnect
            ? ' We’ll open a secure sign-in window.'
            : ' Live connect is finishing setup — your last synced journal still loads if available.'}
        </div>
      )}

      {showAttention && (
        <div className="portfolio-alert">
          {syncMessage || 'Sign into Stake, then tap Connect Stake again.'}
          {loginUrl ? (
            <>
              {' '}
              <a href={loginUrl} target="_blank" rel="noreferrer">
                Open Stake window
              </a>
            </>
          ) : null}
        </div>
      )}

      {connection.status === 'authenticated' && syncStatus !== 'imported' && !hasJournal && (
        <div className="portfolio-alert">
          Stake is connected. Tap Sync to import your history.
        </div>
      )}

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
            <h2>What this means</h2>
            <p className="muted">
              Plain-English read on the imported stats, plus what to carry into your next bets.
            </p>
          </div>
        </div>
        <div className="portfolio-insights">
          <div className="portfolio-insight">{overview.win_loss_text || 'Import settled bets to see this summary.'}</div>
          <div className="portfolio-insight">{overview.roi_text || 'ROI summary will appear here.'}</div>
          <div className="portfolio-insight">{overview.curve_text || 'The curve explanation will appear here.'}</div>
          <div className="portfolio-insight">{overview.market_text || 'Market-family explanation will appear here.'}</div>
        </div>
        {overview.recommendations?.length > 0 && (
          <div className="portfolio-note">
            <h3>Next bet recommendations</h3>
            <div className="portfolio-insights">
              {overview.recommendations.map((tip, idx) => (
                <div key={idx} className="portfolio-insight">{tip}</div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Hit map</h2>
            <p className="muted">
              Immediate read on what hit, what missed, and how much of the imported sample was salvaged by pushes or cashouts.
            </p>
          </div>
        </div>
        <div className="result-strip">
          {resultSummary.map((item) => (
            <div key={item.label} className={`result-pill ${item.cls}`}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>{Math.round((item.value / settledTotal) * 100)}%</small>
            </div>
          ))}
        </div>
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
          <PortfolioCurve points={curve} formatMoney={money} />
        ) : (
          <p className="muted">Sync more than one bet to show the performance curve.</p>
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
                    className={`portfolio-market-fill ${row.profit_value >= 0 ? 'up' : 'down'}`}
                    style={{ width: `${Math.min(100, Math.max(8, Math.abs(row.profit_value) * 10))}%` }}
                  />
                </div>
                <strong className={row.profit_value >= 0 ? 'green' : 'red'}>{money(row.profit_value)}</strong>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Model audit and learning</h2>
            <p className="muted">
              Imported bets are now checked against the app's reconstructed board so you can see whether your own action aligned with the model.
            </p>
          </div>
          <span className={`portfolio-pill ${audit.available ? 'ok' : 'warn'}`}>{audit.available ? 'Auditing live' : 'Needs better mapping'}</span>
        </div>
        {audit.available && (
          <div className="portfolio-grid compact">
            <div className="portfolio-stat">
              <span>Audited legs</span>
              <strong>{audit.audited_legs}</strong>
            </div>
            <div className="portfolio-stat">
              <span>Model agreed</span>
              <strong className="green">{audit.aligned_legs}</strong>
            </div>
            <div className="portfolio-stat">
              <span>Model disliked</span>
              <strong className="red">{audit.against_legs}</strong>
            </div>
            <div className="portfolio-stat">
              <span>Strong edges</span>
              <strong>{audit.strong_edges}</strong>
            </div>
          </div>
        )}
        <div className="portfolio-note">
          <h3>Why accuracy is not jumping fast</h3>
          <p className="muted">
            The model report card now grades the actual bets it recommends (loss-minimize, best single,
            value, parlay) - not just who wins the match. Portfolio sync audits your Stake history against
            that same board.
          </p>
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
        {audit.message && <p className="muted">{audit.message}</p>}
        {syncMessage && (
          <p className={`muted ${showAttention ? 'sync-status-warn' : ''}`}>
            Sync status: <strong>{syncStatus}</strong> - {syncMessage}
          </p>
        )}
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
              <div key={bet.id} className={`portfolio-bet status-${bet.result || bet.status || 'unknown'}`}>
                <div className="portfolio-bet-top">
                  <div>
                    <strong>{bet.fixture_name}</strong>
                    <div className="muted">{bet.league || 'Unknown league'} · {fmtTs(bet.created_at)}</div>
                  </div>
                  <div className="portfolio-bet-badges">
                    <span className="portfolio-pill idle">{bet.bet_type || 'bet'}</span>
                    <span className="portfolio-pill idle">{bet.market_family || 'other'}</span>
                    <span className={`portfolio-pill result-${bet.result || 'unknown'}`}>
                      {bet.result || bet.status || 'unknown'}
                    </span>
                    {bet.model_view?.overall && (
                      <span className={`portfolio-pill model-${bet.model_view.overall}`}>
                        model {bet.model_view.overall}
                      </span>
                    )}
                  </div>
                </div>

                <div className="portfolio-bet-grid">
                  <div>
                    <span>Stake</span>
                    <strong>{bet.stake} {bet.currency}</strong>
                  </div>
                  <div>
                    <span>Payout</span>
                    <strong>{bet.payout ? `${Math.round(bet.payout)} ${bet.currency}` : 'n/a'}</strong>
                  </div>
                  <div>
                    <span>Odds</span>
                    <strong>{bet.combined_odds || bet.potential_multiplier || 'n/a'}</strong>
                  </div>
                  <div>
                    <span>P/L</span>
                    <strong className={(bet.profit_value ?? 0) >= 0 ? 'green' : 'red'}>{money(bet.profit_value)}</strong>
                  </div>
                </div>

                <div className="portfolio-selection-list">
                  {(bet.selections || []).map((sel, idx) => (
                    <div key={`${bet.id}-${idx}`} className="portfolio-selection">
                      <span>{sel.selection || 'Selection'}</span>
                      <small>{sel.fixture_name || bet.fixture_name} · {sel.odds || 'n/a'}</small>
                    </div>
                  ))}
                </div>
                {bet.model_view?.legs?.length > 0 && (
                  <div className="portfolio-model-legs">
                    {bet.model_view.legs.map((leg, idx) => (
                      <div key={`${bet.id}-model-${idx}`} className={`portfolio-model-leg ${leg.tone || 'neutral'}`}>
                        <strong>{leg.verdict_label || 'Model read'}</strong>
                        <span>{leg.label}</span>
                        {leg.edge_pct != null && <small>Edge {leg.edge_pct}% · {Math.round((leg.our_probability || 0) * 100)}% win chance</small>}
                        {leg.tone === 'good' && <small>Good means the model thought the price was worth backing.</small>}
                        {leg.tone === 'bad' && <small>Bad means the model thought the payout was too short for the risk.</small>}
                        {leg.tone === 'neutral' && <small>Neutral means the model saw little edge either way.</small>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
