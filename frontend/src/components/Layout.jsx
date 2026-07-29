import { NavLink, Outlet, Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { checkHealth } from '../api/index'
import { useBankroll, formatINR } from '../context/BankrollContext'
import AgeGate from './AgeGate'
import EntryScreen from './EntryScreen'
import GambitLogo from './GambitLogo'
import { NavIcon } from './Icons'
import './Layout.css'

const NAV = [
  { to: '/app', label: 'Home', icon: 'matches' },
  { to: '/app/model', label: 'Model', icon: 'model' },
  { to: '/app/portfolio', label: 'Portfolio', icon: 'portfolio' },
  { to: '/app/guide', label: 'Guide', icon: 'guide' },
]

export default function Layout() {
  const [status, setStatus] = useState(null)
  const {
    clearSlip, legs, removeLeg, slipMode, slipOdds, slipPayout, slipSingles, slipMsg,
    setLegStake, multiStake, setMultiStake, showMulti,
    singlesStakeTotal, singlesPayoutTotal, totalStake, totalPayout,
    slipOpen, setSlipOpen, slipWidth, settleLeg, confirmPlaced,
  } = useBankroll()
  const [confirmBusy, setConfirmBusy] = useState(false)
  const online = status && status.status !== 'error'

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      checkHealth()
        .then((s) => { if (!cancelled) setStatus(s) })
        .catch(() => { if (!cancelled) setStatus({ status: 'error' }) })
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return (
    <EntryScreen>
      <div className="stake-shell">
        <AgeGate />

        <header className="top-dash">
          <nav className="top-dash-nav">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/app'}
                className={({ isActive }) => (isActive ? 'top-nav-link active' : 'top-nav-link')}
              >
                <NavIcon name={item.icon} />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          <Link to="/app" className="top-dash-brand" aria-label="GAMBIT home">
            <GambitLogo size={44} showWord stacked={false} />
          </Link>

          <div className="top-dash-user">
            <div className={`user-chip ${online ? 'is-on' : 'is-off'}`}>
              <small>API</small>
              <strong>{online ? 'Live' : 'Down'}</strong>
            </div>
            <button
              type="button"
              className={`user-chip slip-toggle-chip ${slipOpen ? 'is-on' : ''}`}
              onClick={() => setSlipOpen(!slipOpen)}
              aria-pressed={slipOpen}
              aria-label={slipOpen ? 'Hide bet slip' : 'Show bet slip'}
            >
              <small>Slip</small>
              <strong>{legs?.length ? `${legs.length}` : (slipOpen ? 'Open' : 'Hide')}</strong>
            </button>
          </div>
        </header>

        <div
          className={`stake-body ${slipOpen ? 'slip-open' : 'slip-closed'}`}
          style={{ '--slip-width': `${slipWidth}px` }}
        >
          <main className="stake-main">
            {/* Pathname only — query (?league=&focus=) must not remount and wipe boards */}
            <div className="route-view" key={typeof location !== 'undefined' ? location.pathname : 'main'}>
              <Outlet />
            </div>
          </main>

          {slipOpen && (
            <aside className="slip-rail" aria-label="Bet slip">
              <div className="slip-rail-head">
                <strong>Bet slip</strong>
                <div className="slip-rail-actions">
                  {legs?.length > 0 && (
                    <button type="button" className="slip-clear" onClick={clearSlip}>Clear</button>
                  )}
                  <button
                    type="button"
                    className="slip-clear"
                    onClick={() => setSlipOpen(false)}
                    aria-label="Collapse bet slip"
                  >
                    Hide
                  </button>
                </div>
              </div>

              {slipMsg && <p className="slip-warn" role="status">{slipMsg}</p>}

              {!legs?.length && (
                <p className="muted slip-empty">
                  Add picks from a board or Recs → Add to bet slip. Mark won/lost so the model learns.
                </p>
              )}

              {legs?.length > 0 && (
                <div className="slip-body">
                  <div className="slip-section-label">Singles</div>
                  <div className="slip-ticket-stack">
                    {(slipSingles || []).map((leg) => (
                      <article key={leg.id} className={`slip-ticket ${leg.result ? `is-${leg.result}` : ''}`}>
                        <div className="slip-ticket-top">
                          <span className="slip-ticket-kind">
                            {leg.result === 'won' ? 'Won' : leg.result === 'lost' ? 'Lost' : 'Single'}
                          </span>
                          <button type="button" className="slip-leg-x" onClick={() => removeLeg(leg.id)} aria-label="Remove">×</button>
                        </div>
                        {leg.marketName && <div className="slip-mkt">{leg.marketName}</div>}
                        <strong className="slip-ticket-pick">{leg.label}</strong>
                        <div className="muted slip-ticket-match">
                          {leg.home}{leg.away ? ` vs ${leg.away}` : ''}
                        </div>
                        <div className="slip-ticket-odds">
                          <span>{Number(leg.odds) > 1 ? `${Number(leg.odds).toFixed(2)}×` : '-'}</span>
                        </div>
                        <div className="slip-ticket-stake-row">
                          <label className="slip-amount">
                            <span className="slip-amount-label">Amount</span>
                            <input
                              type="text"
                              inputMode="decimal"
                              placeholder="₹"
                              value={leg.stake ?? ''}
                              onChange={(e) => setLegStake(leg.id, e.target.value.replace(/[^\d.]/g, ''))}
                              aria-label={`Amount for ${leg.label}`}
                              disabled={Boolean(leg.result)}
                            />
                          </label>
                          {leg.payout != null && (
                            <div className="slip-ticket-payout">
                              <span>Payout</span>
                              <strong className="green">{formatINR(leg.payout)}</strong>
                            </div>
                          )}
                        </div>
                        {!leg.result && (
                          <div className="slip-learn-row">
                            <button type="button" className="slip-learn-btn won" onClick={() => settleLeg(leg.id, true)}>
                              Won
                            </button>
                            <button type="button" className="slip-learn-btn lost" onClick={() => settleLeg(leg.id, false)}>
                              Lost
                            </button>
                          </div>
                        )}
                      </article>
                    ))}
                  </div>

                  {showMulti && (
                    <>
                      <div className="slip-section-label">
                        {slipMode === 'sgm' ? 'Same game multi' : 'Multi'}
                      </div>
                      <article className="slip-ticket slip-ticket--multi">
                        <div className="slip-ticket-top">
                          <span className="slip-ticket-kind">{slipMode === 'sgm' ? 'SGM' : 'Multi'}</span>
                          <span className="green">{slipOdds != null ? `${Number(slipOdds).toFixed(2)}×` : '-'}</span>
                        </div>
                        <ul className="slip-ticket-legs">
                          {(slipSingles || []).map((leg) => (
                            <li key={`m-${leg.id}`}>{leg.label}</li>
                          ))}
                        </ul>
                        <div className="slip-ticket-stake-row">
                          <label className="slip-amount">
                            <span className="slip-amount-label">Amount</span>
                            <input
                              type="text"
                              inputMode="decimal"
                              placeholder="₹"
                              value={multiStake}
                              onChange={(e) => setMultiStake(e.target.value.replace(/[^\d.]/g, ''))}
                              aria-label="Multi amount"
                            />
                          </label>
                          {slipPayout != null && (
                            <div className="slip-ticket-payout">
                              <span>Payout</span>
                              <strong className="green">{formatINR(slipPayout)}</strong>
                            </div>
                          )}
                        </div>
                      </article>
                    </>
                  )}

                  <div className="slip-summary">
                    {singlesStakeTotal > 0 && (
                      <>
                        <div className="slip-summary-row">
                          <span>Singles stake</span>
                          <strong>{formatINR(singlesStakeTotal)}</strong>
                        </div>
                        {singlesPayoutTotal > 0 && (
                          <div className="slip-summary-row">
                            <span>Singles payout</span>
                            <strong className="green">{formatINR(singlesPayoutTotal)}</strong>
                          </div>
                        )}
                      </>
                    )}
                    {showMulti && Number(multiStake) > 0 && (
                      <>
                        <div className="slip-summary-row">
                          <span>Multi stake</span>
                          <strong>{formatINR(Number(multiStake))}</strong>
                        </div>
                        {slipPayout != null && (
                          <div className="slip-summary-row">
                            <span>Multi payout</span>
                            <strong className="green">{formatINR(slipPayout)}</strong>
                          </div>
                        )}
                      </>
                    )}
                    {totalStake > 0 && (
                      <div className="slip-summary-row slip-summary-total">
                        <span>Total stake</span>
                        <strong>{formatINR(totalStake)}</strong>
                      </div>
                    )}
                    {totalPayout > 0 && (
                      <div className="slip-summary-row slip-summary-total">
                        <span>Total payout</span>
                        <strong className="green">{formatINR(totalPayout)}</strong>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="slip-footer">
                {legs?.length > 0 && (
                  <button
                    type="button"
                    className="refresh-btn"
                    style={{ width: '100%', marginBottom: 8 }}
                    disabled={confirmBusy}
                    onClick={async () => {
                      setConfirmBusy(true)
                      try {
                        await confirmPlaced()
                      } catch {
                        /* message set in context */
                      } finally {
                        setConfirmBusy(false)
                      }
                    }}
                  >
                    {confirmBusy ? 'Saving…' : 'Confirm I placed this'}
                  </button>
                )}
                <p className="sidebar-disclaimer">18+ · Bet responsibly.</p>
              </div>
            </aside>
          )}

          {!slipOpen && (
            <button
              type="button"
              className="slip-fab"
              onClick={() => setSlipOpen(true)}
              aria-label="Open bet slip"
            >
              Slip{legs?.length ? ` · ${legs.length}` : ''}
            </button>
          )}
        </div>

        <nav className="bottom-nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/app'}
              className={({ isActive }) => (isActive ? 'bottom-item active' : 'bottom-item')}
            >
              <span className="nav-icon"><NavIcon name={item.icon} /></span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </EntryScreen>
  )
}
