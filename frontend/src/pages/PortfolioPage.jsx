import { useEffect, useMemo, useState } from 'react'
import {
  connectPortfolioSession,
  disconnectPortfolioSession,
  fetchErrorMessage,
  fetchPortfolioState,
  checkHealth,
  refreshPortfolioSnapshot,
  updatePortfolioPrivacy,
  addManualPortfolioBet,
  updatePortfolioBetResult,
  connectStakeApiToken,
  retryStakeTokenSync,
} from '../api'
import PortfolioCurve from '../components/PortfolioCurve'
import { useEntryReady } from '../components/EntryScreen'
import { useAuth } from '../context/AuthContext'
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
  const [manual, setManual] = useState({
    home: '', away: '', selection: '', odds: '', stake: '', result: 'open', market: 'manual',
  })
  const [manualBusy, setManualBusy] = useState(false)
  const [stakeToken, setStakeToken] = useState('')
  const [tokenBusy, setTokenBusy] = useState(false)
  const [betsShown, setBetsShown] = useState(12)
  const { user, ready, openAuth } = useAuth()
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
        // Host has no live browser path; journal still works from last sync / manual bets.
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
        // Background auto-settle may flip open → won/lost shortly after load.
        const openN = (next?.portfolio?.bets || []).filter((b) => b.result === 'open').length
        if (openN > 0) {
          setTimeout(() => {
            if (!mounted) return
            fetchPortfolioState().then((fresh) => { if (mounted) setState(fresh) }).catch(() => {})
          }, 8000)
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
  const syncStatus = connection.last_sync_status || 'ready'
  const betCount = Array.isArray(portfolio.bets) ? portfolio.bets.length : 0
  const hasJournal = betCount > 0 || syncStatus === 'imported' || syncStatus === 'confirmed' || connection.status === 'relay'
  const syncMessage = connection.last_sync_message || ''
  const loginUrl = connection.login_url || browser.login_url || ''
  const stakeLoggedIn = connection.status === 'authenticated'
    || connection.status === 'relay'
    || Boolean(browser.have_auth_token)
  // Always allow Connect / Sync clicks; backend returns a clear error if Stake is unavailable.
  const canSync = portfolioReady
  const needsSignIn = ['awaiting_login', 'auth_required'].includes(connection.status)
    || syncStatus === 'auth_required'
  const showStatusError = Boolean(err)
    || syncStatus === 'error'
    || needsSignIn
    || (cloudStake && !stakeLive && !hasJournal)
  const statusBanner = err || syncMessage || ''
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
  const sportRows = portfolio.by_sport || []
  const monthlyForm = portfolio.monthly_form || []
  const audit = portfolio.model_audit || {}
  const learning = portfolio.learning_feedback || {}
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
        portfolio_enabled: patch.portfolio_enabled ?? privacy.portfolio_enabled ?? true,
        risk_acknowledged: patch.risk_acknowledged ?? privacy.risk_acknowledged ?? true,
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
      if (message && (status === 'error' || status === 'auth_required' || status === 'needs_reconnect' || status === 'setup')) {
        setErr(message)
      }
      if (key === 'snapshot' && status && !['imported', 'confirmed', 'authenticated'].includes(status) && message) {
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
            Sign in, connect Stake with an API token, or confirm slip bets. Finished matches settle won or lost automatically.
          </p>
          {portfolio.profile?.summary && (
            <p className="portfolio-hero-summary">{portfolio.profile.summary}</p>
          )}
        </div>
        <div className="portfolio-hero-actions">
          {stakeLoggedIn ? (
            <button
              className="refresh-btn"
              onClick={() => {
                if (!user) {
                  openAuth('login')
                  return
                }
                runAction('snapshot', refreshPortfolioSnapshot)
              }}
              disabled={!user || !canSync || busy === 'snapshot'}
              title={!user ? 'Sign in first' : 'Refresh Stake bet history'}
            >
              {busy === 'snapshot' ? 'Refreshing…' : 'Sync Stake'}
            </button>
          ) : (
            <button
              className="refresh-btn"
              onClick={() => {
                if (!user) {
                  openAuth('login')
                  return
                }
                const el = document.getElementById('stake-connect-panel')
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
                else runAction('connect', connectPortfolioSession)
              }}
              disabled={busy === 'connect'}
              title="Connect your Stake account"
            >
              {busy === 'connect' ? 'Connecting…' : (user ? 'Connect Stake' : 'Sign in to connect Stake')}
            </button>
          )}
        </div>
      </header>

      {!stakeLoggedIn ? (
      <section className="portfolio-card fade-up" id="stake-connect-panel">
        <div className="portfolio-card-head">
          <div>
            <h2>Connect Stake</h2>
            <p className="muted">
              No installs. Create a token on Stake, paste it here, and we import your bet history.
            </p>
          </div>
        </div>
        {!user && (
          <p className="muted">
            <button type="button" className="refresh-btn" onClick={() => openAuth('signup')}>
              Create a Gambit account
            </button>
            {' '}first so your journal stays private to you.
          </p>
        )}
        <div className="stake-token-box">
          <ol className="muted" style={{ margin: 0, paddingLeft: '1.2rem', lineHeight: 1.5 }}>
            <li>
              <a href="https://stake.com/?tab=login&modal=auth" target="_blank" rel="noreferrer">
                Sign in on Stake
              </a>
            </li>
            <li>
              Open{' '}
              <a href="https://stake.com/settings/security" target="_blank" rel="noreferrer">
                Settings → Security → API Tokens
              </a>
              {' '}and create a token
            </li>
            <li>Paste the token below and tap Connect</li>
          </ol>
          <input
            type="password"
            autoComplete="off"
            placeholder="Paste Stake API token"
            value={stakeToken}
            onChange={(e) => setStakeToken(e.target.value.trim())}
          />
          <div className="stake-token-actions">
            <button
              type="button"
              className="refresh-btn"
              disabled={tokenBusy || !stakeToken || !user}
              onClick={async () => {
                if (!user) {
                  openAuth('login')
                  return
                }
                setTokenBusy(true)
                setErr('')
                try {
                  const next = await connectStakeApiToken(stakeToken)
                  setState(next)
                  setStakeToken('')
                  const status = next?.connection?.last_sync_status
                  if (status === 'queued') {
                    let ticks = 0
                    const id = setInterval(() => {
                      ticks += 1
                      fetchPortfolioState()
                        .then((fresh) => {
                          setState(fresh)
                          const s = fresh?.connection?.last_sync_status
                          if (s && s !== 'queued') clearInterval(id)
                        })
                        .catch(() => {})
                      if (ticks >= 24) clearInterval(id)
                    }, 8000)
                  }
                } catch (e) {
                  setErr(fetchErrorMessage(e, 'Could not connect Stake token.'))
                } finally {
                  setTokenBusy(false)
                }
              }}
            >
              {tokenBusy ? 'Connecting…' : 'Connect with token'}
            </button>
          </div>
        </div>
        {syncStatus === 'queued' && (
          <p className="muted" style={{ marginTop: '0.75rem' }}>
            Import queued
            {state?.odds_link?.online ? ' · odds link online' : ' · waiting for odds link'}
            . Stay signed in — status updates automatically.
            {' '}
            <button
              type="button"
              className="refresh-btn"
              disabled={tokenBusy}
              onClick={async () => {
                setTokenBusy(true)
                try {
                  const next = await retryStakeTokenSync()
                  setState(next)
                } catch (e) {
                  setErr(fetchErrorMessage(e, 'Retry failed.'))
                } finally {
                  setTokenBusy(false)
                }
              }}
            >
              Retry import
            </button>
          </p>
        )}
      </section>
      ) : (
      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Stake connected</h2>
            <p className="muted">
              Token saved to your account. Use Sync Stake to refresh history — no need to paste the token again.
            </p>
          </div>
          <span className="portfolio-pill ok">Connected</span>
        </div>
        <details className="portfolio-reconnect">
          <summary className="muted">Replace API token</summary>
          <div className="stake-token-box" style={{ marginTop: '0.75rem' }}>
            <input
              type="password"
              autoComplete="off"
              placeholder="Paste a new Stake API token"
              value={stakeToken}
              onChange={(e) => setStakeToken(e.target.value.trim())}
            />
            <div className="stake-token-actions">
              <button
                type="button"
                className="refresh-btn"
                disabled={tokenBusy || !stakeToken || !user}
                onClick={async () => {
                  setTokenBusy(true)
                  setErr('')
                  try {
                    const next = await connectStakeApiToken(stakeToken)
                    setState(next)
                    setStakeToken('')
                  } catch (e) {
                    setErr(fetchErrorMessage(e, 'Could not update Stake token.'))
                  } finally {
                    setTokenBusy(false)
                  }
                }}
              >
                {tokenBusy ? 'Saving…' : 'Update token'}
              </button>
            </div>
          </div>
        </details>
      </section>
      )}

      {(showStatusError || statusBanner) && (
        <div className={`portfolio-alert ${showStatusError ? 'error' : ''}`}>
          {statusBanner || 'Connect Stake or confirm bets from your slip to build your journal.'}
          {loginUrl ? (
            <>
              {' '}
              <a href={loginUrl} target="_blank" rel="noreferrer">Open Stake window</a>
            </>
          ) : null}
        </div>
      )}

      {hasJournal && !showStatusError && (
        <div className="portfolio-alert">
          {syncMessage || `Journal ready${betCount ? ` · ${betCount} bets` : ''}.`}
          {connection.last_sync_at ? ` Updated ${fmtTs(connection.last_sync_at)}.` : ''}
        </div>
      )}

      {!ready ? null : connection.status === 'authenticated' && syncStatus !== 'imported' && !hasJournal && (
        <div className="portfolio-alert">
          Stake is connected. Tap Sync Stake to import your history.
        </div>
      )}

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
        {!!sportRows.length && (
          <div className="portfolio-note">
            <h3>By sport</h3>
            <div className="portfolio-grid compact">
              {sportRows.map((row) => (
                <div key={row.sport} className="portfolio-stat">
                  <span>{row.sport}</span>
                  <strong className={row.profit_value >= 0 ? 'green' : 'red'}>{money(row.profit_value)}</strong>
                  <small className="muted">{row.count} bets · {row.hit_rate_pct}% hit · {row.roi_pct}% ROI</small>
                </div>
              ))}
            </div>
          </div>
        )}
        {!!monthlyForm.length && (
          <div className="portfolio-note">
            <h3>Recent form</h3>
            <div className="portfolio-market-list">
              {monthlyForm.map((row) => (
                <div key={row.month} className="portfolio-market-row">
                  <div className="portfolio-market-copy">
                    <strong>{row.month}</strong>
                    <small>{row.count} bets graded</small>
                  </div>
                  <strong className={row.profit_value >= 0 ? 'green' : 'red'}>{money(row.profit_value)}</strong>
                </div>
              ))}
            </div>
          </div>
        )}
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
        {learning.available && (
          <div className="portfolio-note">
            <h3>What your real results are teaching the model</h3>
            <div className="portfolio-grid compact">
              <div className="portfolio-stat">
                <span>Model-backed bets</span>
                <strong>{learning.follow_model_bets ?? 0}</strong>
                <small className="muted">{learning.follow_model_hit_rate_pct ?? '—'}% hit · {learning.follow_model_roi_pct ?? '—'}% ROI</small>
              </div>
              <div className="portfolio-stat">
                <span>Model-fade bets</span>
                <strong>{learning.fade_model_bets ?? 0}</strong>
                <small className="muted">{learning.fade_model_hit_rate_pct ?? '—'}% hit · {learning.fade_model_roi_pct ?? '—'}% ROI</small>
              </div>
              <div className="portfolio-stat">
                <span>Audited settled bets</span>
                <strong>{learning.audited_bets ?? 0}</strong>
                <small className="muted">Only bets matched back to the model desk count here.</small>
              </div>
              <div className="portfolio-stat">
                <span>Recent audited P/L</span>
                <strong className={(learning.recent_profit_value ?? 0) >= 0 ? 'green' : 'red'}>{money(learning.recent_profit_value)}</strong>
                <small className="muted">Last audited stretch</small>
              </div>
            </div>
            {!!learning.recommendations?.length && (
              <div className="portfolio-insights" style={{ marginTop: '0.9rem' }}>
                {learning.recommendations.map((tip, idx) => (
                  <div key={idx} className="portfolio-insight">{tip}</div>
                ))}
              </div>
            )}
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
          <p className={`muted ${showStatusError ? 'sync-status-warn' : ''}`}>
            Sync status: <strong>{syncStatus}</strong> - {syncMessage}
          </p>
        )}
        {!stakeLive && !loginUrl && (
          <p className="muted">
            Live browser login is only available when a supported remote browser path is configured. Until then, keep using the Stake API token import.
          </p>
        )}
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Add a past bet</h2>
            <p className="muted">
              Log a finished bet from any book. For upcoming picks, use Confirm I placed this on the slip — results auto-fill when the match ends.
            </p>
          </div>
        </div>
        <form
          className="portfolio-manual-form"
          onSubmit={async (e) => {
            e.preventDefault()
            setManualBusy(true)
            setErr('')
            try {
              const next = await addManualPortfolioBet({
                home: manual.home,
                away: manual.away,
                selection: manual.selection,
                market: manual.market || 'manual',
                odds: manual.odds ? Number(manual.odds) : null,
                stake: Number(manual.stake),
                result: manual.result || 'open',
              })
              setState(next)
              setManual({ home: '', away: '', selection: '', odds: '', stake: '', result: 'open', market: 'manual' })
            } catch (ex) {
              setErr(fetchErrorMessage(ex, 'Could not save manual bet.'))
            } finally {
              setManualBusy(false)
            }
          }}
        >
          <label className="portfolio-check compact">
            <span>Home</span>
            <input value={manual.home} onChange={(e) => setManual((m) => ({ ...m, home: e.target.value }))} required />
          </label>
          <label className="portfolio-check compact">
            <span>Away</span>
            <input value={manual.away} onChange={(e) => setManual((m) => ({ ...m, away: e.target.value }))} required />
          </label>
          <label className="portfolio-check compact">
            <span>Selection</span>
            <input value={manual.selection} onChange={(e) => setManual((m) => ({ ...m, selection: e.target.value }))} required />
          </label>
          <label className="portfolio-check compact">
            <span>Odds</span>
            <input value={manual.odds} onChange={(e) => setManual((m) => ({ ...m, odds: e.target.value.replace(/[^\d.]/g, '') }))} placeholder="2.10" />
          </label>
          <label className="portfolio-check compact">
            <span>Stake</span>
            <input value={manual.stake} onChange={(e) => setManual((m) => ({ ...m, stake: e.target.value.replace(/[^\d.]/g, '') }))} required placeholder="100" />
          </label>
          <label className="portfolio-check compact">
            <span>Result</span>
            <select value={manual.result} onChange={(e) => setManual((m) => ({ ...m, result: e.target.value }))}>
              <option value="open">Open</option>
              <option value="won">Won</option>
              <option value="lost">Lost</option>
              <option value="push">Push</option>
            </select>
          </label>
          <button className="refresh-btn" type="submit" disabled={manualBusy}>
            {manualBusy ? 'Saving…' : 'Add to journal'}
          </button>
        </form>
      </section>

      <section className="portfolio-card fade-up">
        <div className="portfolio-card-head">
          <div>
            <h2>Bet journal</h2>
            <p className="muted">
              Stake imports plus confirmed slip bets and manual history.
            </p>
          </div>
          <span className={`portfolio-pill ${portfolio.bets?.length ? 'ok' : 'idle'}`}>
            {portfolio.bets?.length ? `${portfolio.bets.length} loaded` : 'No bets yet'}
          </span>
        </div>

        {!portfolio.bets?.length ? (
          <p className="muted">
            No bets yet. Confirm a slip with amounts, add a past bet above, or import your Stake history with an API token.
          </p>
        ) : (
          <>
          <div className="portfolio-bets">
            {portfolio.bets.slice(0, betsShown).map((bet) => (
              <div key={bet.id} className={`portfolio-bet status-${bet.result || bet.status || 'unknown'}`}>
                <div className="portfolio-bet-top">
                  <div>
                    <strong>{bet.fixture_name}</strong>
                    <div className="muted">{(bet.source || 'stake')} · {bet.league || 'Unknown league'} · {fmtTs(bet.created_at)}</div>
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
                {bet.result === 'open' && (
                  <div className="portfolio-inline-actions">
                    <span className="muted">
                      Waiting for final score. Won/lost updates automatically when the match finishes.
                    </span>
                    <button
                      type="button"
                      className="refresh-btn"
                      onClick={() => runAction('bet-won', () => updatePortfolioBetResult(bet.id, 'won'))}
                    >
                      Override won
                    </button>
                    <button
                      type="button"
                      className="refresh-btn"
                      onClick={() => runAction('bet-lost', () => updatePortfolioBetResult(bet.id, 'lost'))}
                    >
                      Override lost
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
          {portfolio.bets.length > betsShown && (
            <button
              type="button"
              className="refresh-btn"
              style={{ marginTop: '0.75rem' }}
              onClick={() => setBetsShown((n) => n + 20)}
            >
              Show more ({portfolio.bets.length - betsShown} left)
            </button>
          )}
          {betsShown > 12 && portfolio.bets.length > 12 && (
            <button
              type="button"
              className="refresh-btn"
              style={{ marginTop: '0.5rem', marginLeft: '0.5rem' }}
              onClick={() => setBetsShown(12)}
            >
              Show less
            </button>
          )}
          </>
        )}
      </section>
    </div>
  )
}
