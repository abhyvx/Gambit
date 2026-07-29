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
  { to: '/app/guide', label: 'How it works', icon: 'guide' },
]

export default function Layout() {
  const [status, setStatus] = useState(null)
  const {
    clearSlip, legs, removeLeg, slipMode, slipOdds, slipPayout, slipSingles, slipMsg,
    setLegStake, multiStake, setMultiStake, showMulti,
    singlesStakeTotal, singlesPayoutTotal, totalStake, totalPayout,
  } = useBankroll()
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
          </div>
        </header>

        <div className="stake-body">
          <main className="stake-main">
            <div className="route-view" key={location.pathname + location.search}>
              <Outlet />
            </div>
          </main>

          <aside className="slip-rail" aria-label="Bet slip">
            <div className="slip-rail-head">
              <strong>Bet slip</strong>
              {legs?.length > 0 && (
                <button type="button" className="slip-clear" onClick={clearSlip}>Clear</button>
              )}
            </div>

            {slipMsg && <p className="slip-warn" role="status">{slipMsg}</p>}

            {!legs?.length && (
              <p className="muted slip-empty">
                Add picks from a board. Each single is its own ticket; two or more also build a multi.
              </p>
            )}

            {legs?.length > 0 && (
              <div className="slip-body">
                <div className="slip-section-label">Singles</div>
                <div className="slip-ticket-stack">
                  {(slipSingles || []).map((leg) => (
                    <article key={leg.id} className="slip-ticket">
                      <div className="slip-ticket-top">
                        <span className="slip-ticket-kind">Single</span>
                        <button type="button" className="slip-leg-x" onClick={() => removeLeg(leg.id)} aria-label="Remove">×</button>
                      </div>
                      {leg.marketName && <div className="slip-mkt">{leg.marketName}</div>}
                      <strong className="slip-ticket-pick">{leg.label}</strong>
                      <div className="muted slip-ticket-match">
                        {leg.home}{leg.away ? ` vs ${leg.away}` : ''}
                      </div>
                      <div className="slip-ticket-odds">
                        <span>{Number(leg.odds) > 1 ? `${Number(leg.odds).toFixed(2)}×` : '—'}</span>
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
                          />
                        </label>
                        <div className="slip-ticket-payout">
                          <span>Payout</span>
                          <strong className="green">{leg.payout != null ? formatINR(leg.payout) : '—'}</strong>
                        </div>
                      </div>
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
                        <span className="green">{slipOdds != null ? `${Number(slipOdds).toFixed(2)}×` : '—'}</span>
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
                        <div className="slip-ticket-payout">
                          <span>Payout</span>
                          <strong className="green">{slipPayout != null ? formatINR(slipPayout) : '—'}</strong>
                        </div>
                      </div>
                    </article>
                  </>
                )}

                <div className="slip-summary">
                  <div className="slip-summary-row">
                    <span>Singles stake</span>
                    <strong>{singlesStakeTotal > 0 ? formatINR(singlesStakeTotal) : '—'}</strong>
                  </div>
                  <div className="slip-summary-row">
                    <span>Singles payout</span>
                    <strong className="green">{singlesPayoutTotal > 0 ? formatINR(singlesPayoutTotal) : '—'}</strong>
                  </div>
                  {showMulti && (
                    <>
                      <div className="slip-summary-row">
                        <span>Multi stake</span>
                        <strong>{Number(multiStake) > 0 ? formatINR(Number(multiStake)) : '—'}</strong>
                      </div>
                      <div className="slip-summary-row">
                        <span>Multi payout</span>
                        <strong className="green">{slipPayout != null ? formatINR(slipPayout) : '—'}</strong>
                      </div>
                    </>
                  )}
                  <div className="slip-summary-row slip-summary-total">
                    <span>Total stake</span>
                    <strong>{totalStake > 0 ? formatINR(totalStake) : '—'}</strong>
                  </div>
                  <div className="slip-summary-row slip-summary-total">
                    <span>Total payout</span>
                    <strong className="green">{totalPayout > 0 ? formatINR(totalPayout) : '—'}</strong>
                  </div>
                </div>
              </div>
            )}

            <div className="slip-footer">
              <p className="sidebar-disclaimer">18+ · Bet responsibly.</p>
            </div>
          </aside>
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
