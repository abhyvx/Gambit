import { useState, useEffect } from 'react'
import { formatINR, useBankroll } from '../context/BankrollContext'
import { fetchStakeOdds } from '../api/index'
import AnimatedNumber from './AnimatedNumber'
import BetBuilder from './BetBuilder'

const LEGACY_STRATEGY_KEYS = [
  { key: 'min_loss', label: 'Loss-minimizing', icon: '📉' },
  { key: 'singles_focus', label: 'One best bet', icon: '🎯' },
  { key: 'value', label: 'Value-for-money', icon: '💰' },
  { key: 'smart_parlay', label: 'Parlays', icon: '🔗' },
]

const ROLE_META = {
  main: { label: 'MAIN', icon: '🎯' },
  support: { label: 'SUPPORT', icon: '🛡️' },
  extra: { label: 'EXTRA', icon: '➕' },
  parlay_leg: { label: 'LEG', icon: '🔗' },
}

const RISK_LABEL = { low: 'Low risk', medium: 'Medium', high: 'Higher risk' }

const signedINR = (n) => `${n >= 0 ? '+' : ''}${formatINR(n)}`

function normalizePlans(slip, strategyKey) {
  const fromPlans = slip?.strategy_plans?.[strategyKey]
  if (Array.isArray(fromPlans) && fromPlans.length) {
    return fromPlans.filter((s) => s.legs?.length)
  }
  const raw = slip?.strategies?.[strategyKey]
  if (Array.isArray(raw)) return raw.filter((s) => s.legs?.length)
  if (raw?.legs?.length) return [raw]
  return []
}

function ScenarioCard({ title, data }) {
  if (!data) return null
  const profit = data.profit_inr
  const cls = profit > 0 ? 'scenario-good' : profit < 0 ? 'scenario-bad' : 'scenario-neutral'
  return (
    <div className={`scenario-card ${cls}`}>
      <strong className="scenario-title">{title || data.label}</strong>
      <div className="scenario-profit">
        <AnimatedNumber value={profit} format={signedINR} />
      </div>
      <p>{data.description}</p>
    </div>
  )
}

export default function MatchSlipPanel({ slip, home, away, fanPrediction, status, score }) {
  const { perMatchBudget } = useBankroll()
  const [tab, setTab] = useState('slip')
  const [strategyKey, setStrategyKey] = useState(slip?.recommended_strategy || 'min_loss')
  const [optionIndex, setOptionIndex] = useState(0)
  const [stake, setStake] = useState(null)
  const [stakeLoading, setStakeLoading] = useState(false)
  const categories = slip?.options_by_category || {}

  useEffect(() => {
    if (slip?.recommended_strategy) setStrategyKey(slip.recommended_strategy)
    setOptionIndex(0)
  }, [slip?.match_id, slip?.recommended_strategy])

  useEffect(() => {
    if (!home || !away || status === 'completed') return
    let cancelled = false
    setStakeLoading(true)
    setStake(null)
    fetchStakeOdds({ home, away, budgetInr: perMatchBudget })
      .then((d) => { if (!cancelled) setStake(d) })
      .catch(() => { if (!cancelled) setStake({ available: false, reason: 'Stake request failed from this network.', categories: [] }) })
      .finally(() => { if (!cancelled) setStakeLoading(false) })
    return () => { cancelled = true }
  }, [home, away, perMatchBudget, status])

  if (!slip && status === 'completed') {
    return (
      <div className="slip-panel">
        <div className="result-banner">
          <span className="result-label">FINAL</span>
          <strong>{score}</strong>
        </div>
        <p className="muted">Game over — no bets.</p>
      </div>
    )
  }

  if (!slip) return null

  const planOptions = normalizePlans(slip, strategyKey)
  const strategy = planOptions[optionIndex] || planOptions[0] || slip.active_strategy || {}
  const isSkip = slip.verdict === 'SKIP_MATCH' || slip.recommended_strategy === 'skip'
  const showSkipBanner = isSkip || slip.skip_recommended
  const gameProfile = slip.game_profile || {}
  const scenarios = strategy?.scenarios || slip.payout_scenarios || {}
  const factors = slip.factor_analysis || {}
  const activeLegs = (strategy?.legs || []).filter((l) => l.stake_inr > 0 || l.role === 'parlay_leg')
  const isParlay = strategy?.slip_type === 'parlay' || strategyKey === 'smart_parlay'

  const TABS = [
    { id: 'slip', label: 'Bet slips' },
    { id: 'build', label: '🎯 Build slip' },
    { id: 'stake', label: '💸 Stake odds', badge: stakeLoading ? '…' : stake?.available ? '🟢' : null },
    { id: 'factors', label: 'Analysis' },
    { id: 'players', label: 'Scorers' },
    { id: 'all', label: 'All markets' },
  ]

  return (
    <div className="slip-panel">
      {gameProfile.narrative && (
        <div className="profile-box">
          <h5><span className="profile-chip">{(gameProfile.style || 'game').replace(/_/g, ' ')}</span> game profile</h5>
          <p>{gameProfile.narrative}</p>
          <p className="muted">Loss-min = spread only (2–3 small bets, 72%+ kept) · Singles live under One best bet</p>
        </div>
      )}

      {fanPrediction && (
        <div className="fan-take-box">
          <h5>🗣️ Fan read</h5>
          <p>{fanPrediction}</p>
        </div>
      )}

      {factors.factors_analyzed > 0 && (
        <div className="factor-banner">
          <strong><AnimatedNumber value={factors.factors_analyzed} format={(n) => Math.round(n).toLocaleString()} /> factor checks</strong>
          <span> — {factors.summary}</span>
        </div>
      )}

      {showSkipBanner && (
        <div className={`skip-banner ${isSkip ? 'skip-hard' : 'skip-caution'}`}>
          <strong>{isSkip ? '⛔ SKIP THIS MATCH' : '⚠️ CAUTION — THIN EDGE'}</strong>
          <p>{slip.skip_reason || (isSkip
            ? `Keep all ${formatINR(slip.budget_inr)}. We couldn't find a bet where you're likely to come out ahead.`
            : 'Most betting combinations still lean toward a loss on the most-likely outcome. Only bet if you accept that risk.')}</p>
        </div>
      )}

      <div className="slip-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? 'active' : ''}
            onClick={() => setTab(t.id)}
            role="tab"
            aria-selected={tab === t.id}
          >
            {t.label}{t.badge ? ` ${t.badge}` : ''}
          </button>
        ))}
      </div>

      {tab === 'slip' && (
        <div className="slip-content slip-tab-content" key="slip">
          <div className="strategy-picker">
            {LEGACY_STRATEGY_KEYS.map((s) => {
              const count = normalizePlans(slip, s.key).length
              return (
                <button
                  key={s.key}
                  className={strategyKey === s.key ? 'strategy-btn active' : 'strategy-btn'}
                  onClick={() => { setStrategyKey(s.key); setOptionIndex(0) }}
                >
                  <span className="strategy-icon" aria-hidden>{s.icon}</span>
                  <span className="strategy-label">{s.label}</span>
                  {count > 1 && <span className="strategy-tag">{count} options</span>}
                </button>
              )
            })}
          </div>

          {planOptions.length > 0 && (
            <div className="slip-options-list">
              <h5 className="options-list-head">
                {planOptions.length} betting slip{planOptions.length > 1 ? 's' : ''} — pick one
              </h5>
              <div className="strategy-picker option-picker">
                {planOptions.map((opt, i) => {
                  const likely = opt.scenarios?.likely_case?.profit_inr
                  return (
                    <button
                      key={opt.option_id || `${strategyKey}-${i}`}
                      className={optionIndex === i ? 'strategy-btn active option-btn' : 'strategy-btn option-btn'}
                      onClick={() => setOptionIndex(i)}
                    >
                      <span className="strategy-label">{opt.option_label || `Option ${i + 1}`}</span>
                      <span className="strategy-tag slip-type-tag">
                        {opt.slip_type_label || (opt.leg_count === 1 ? 'Single bet' : `${opt.leg_count}-leg`)}
                      </span>
                      {opt.is_recommended_option && <span className="strategy-tag rec">Top pick</span>}
                      {opt.option_summary && <span className="option-summary">{opt.option_summary}</span>}
                      {opt.win_probability_pct != null && (
                        <span className="option-likely likely-good">
                          Win chance: {opt.win_probability_pct}%
                          {opt.confidence_label ? ` · ${opt.confidence_label}` : ''}
                        </span>
                      )}
                      {likely != null && (
                        <span className={`option-likely ${likely >= 0 ? 'likely-good' : 'likely-bad'}`}>
                          Most likely: {signedINR(likely)}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {planOptions.length === 0 && strategyKey === 'min_loss' && (
            <div className="skip-note">
              <strong>No loss-minimizing plan for this match.</strong>
              Nothing clears our spread/safety bar (62%+ per leg, 72%+ kept in pocket).
              Singles need 68%+ confidence — otherwise skip.
            </div>
          )}

          {planOptions.length === 0 && strategyKey === 'smart_parlay' && (
            <div className="skip-note">
              <strong>No +EV parlay for this match.</strong>
              Legs didn&apos;t combine into a parlay worth the risk at Stake&apos;s prices.
            </div>
          )}

          {planOptions.length === 0 && strategyKey !== 'min_loss' && strategyKey !== 'smart_parlay' && !isSkip && (
            <div className="skip-note">
              <strong>No plans in this tab.</strong> Try another strategy or skip this match.
            </div>
          )}

          <div className={`odds-origin-banner ${slip.stake_priced ? 'origin-stake' : 'origin-book'}`}>
            <span className="origin-dot" aria-hidden />
            {slip.stake_priced
              ? `Only Stake-placeable bets — ${slip.stake_repriced_count} markets matched at real Stake prices`
              : "Live-book estimate — verify each pick exists on Stake before betting"}
          </div>

          {strategyKey === 'min_loss' && strategy?.reserve_inr != null && (
            <div className="loss-min-banner">
              <strong>Capital preservation plan</strong>
              <span>
                {formatINR(strategy.reserve_inr)} kept ({Math.round((strategy.reserve_inr / slip.budget_inr) * 100)}%)
                · {formatINR(strategy.total_stake_inr)} across {activeLegs.length} bets
              </span>
            </div>
          )}

          <div className={`slip-verdict slip-${slip.verdict?.toLowerCase()}`}>
            <div className="slip-verdict-head">
              <h4>{strategy?.name || slip.headline}</h4>
              {strategy?.slip_type_label && (
                <span className={`slip-type-badge slip-type-${strategy.slip_type || 'single'}`}>
                  {strategy.slip_type_label}
                </span>
              )}
            </div>
            <p className="plain-slip">{strategy?.description || slip.plain_english}</p>
            {strategy?.why && <p className="strategy-why">{strategy.why}</p>}
            {strategy?.risk && <p className="muted slip-risk-line">{RISK_LABEL[strategy.risk] || strategy.risk}</p>}
          </div>

          {planOptions.length > 1 && (
            <p className="muted slip-hint">
              Each option is a different combination of bets — don&apos;t stack them all on one match.
            </p>
          )}

          <div className="slip-budget-row">
            <div className="budget-tile">
              <span className="bt-label">Budget</span>
              <strong>{formatINR(slip.budget_inr)}</strong>
            </div>
            <div className="budget-tile">
              <span className="bt-label">Betting</span>
              <strong>{formatINR(strategy?.total_stake_inr || strategy?.stake_inr || 0)}</strong>
            </div>
            <div className="budget-tile keep">
              <span className="bt-label">In your pocket</span>
              <strong className="green">{formatINR(strategy?.reserve_inr ?? slip.keep_unbet_inr)}</strong>
            </div>
          </div>

          {activeLegs.length > 0 ? (
            <div className="slip-legs">
              {activeLegs.map((leg, i) => (
                <div key={i} className={`leg-card role-${leg.role}`}>
                  <div className="leg-top">
                    <span className="leg-role-pill">
                      {(ROLE_META[leg.role] || ROLE_META.parlay_leg).icon}{' '}
                      {(ROLE_META[leg.role] || ROLE_META.parlay_leg).label}
                    </span>
                    <span className="leg-type-pill">
                      {isParlay ? `Parlay leg ${i + 1}` : activeLegs.length === 1 ? 'Single bet' : `Leg ${i + 1} of ${activeLegs.length}`}
                    </span>
                    <span className="leg-winpct">{leg.our_probability_pct}% <small>win chance</small></span>
                  </div>
                  <div className="leg-main">
                    <strong className="leg-label">{leg.label}</strong>
                    <span className={`odds-pill ${leg.odds_source === 'stake' ? 'is-stake' : 'is-est'}`}>
                      {leg.odds}x {leg.odds_source === 'stake' ? '🟢 Stake' : 'est.'}
                    </span>
                  </div>
                  {leg.stake_inr > 0 && (
                    <div className="leg-meta">
                      <span>Stake <strong>{formatINR(leg.stake_inr)}</strong></span>
                      {leg.payout_text && <span className="leg-payout">{leg.payout_text}</span>}
                      {leg.return_inr != null && <span>Returns <strong className="green">{formatINR(leg.return_inr)}</strong></span>}
                    </div>
                  )}
                  {leg.reason && <p className="leg-reason">{leg.reason}</p>}
                </div>
              ))}
            </div>
          ) : isSkip ? (
            <div className="skip-note skip-note-hard">
              <strong>Skip this game.</strong> {slip.skip_reason || `Keep all ${formatINR(slip.budget_inr)}.`}
            </div>
          ) : (
            <div className="skip-note">
              <strong>No bets in this option.</strong> Pick another slip above or try a different tab.
            </div>
          )}

          {isParlay && strategy?.combined_odds && activeLegs.length > 0 && (
            <div className="parlay-odds">
              <span>Combined stake</span>
              <strong>{formatINR(strategy.stake_inr || strategy.total_stake_inr)}</strong>
              <span>Combined payout</span>
              <strong>{strategy.combined_odds}x</strong>
              <span className="parlay-prob">{strategy.combined_probability_pct}% chance all {activeLegs.length} hit</span>
            </div>
          )}

          <div className="scenarios-block">
            <h5 className="scenarios-head">Your payout scenarios</h5>
            <div className="scenarios-grid">
              <ScenarioCard title="😬 Worst case" data={scenarios.worst_case} />
              <ScenarioCard title="📊 Most likely" data={scenarios.likely_case} />
              <ScenarioCard title="🎉 Best case" data={scenarios.best_case} />
              {(scenarios.expected_value_inr != null || strategy?.expected_value_inr != null) && (
                <div className="scenario-card scenario-neutral">
                  <strong className="scenario-title">📈 Long-run average</strong>
                  <div className="scenario-profit">
                    <AnimatedNumber value={scenarios.expected_value_inr ?? strategy?.expected_value_inr} format={formatINR} />
                  </div>
                  <p>Negative = you&apos;d lose money on average. We skip slips that fail this check.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === 'build' && (
        status === 'completed'
          ? <p className="muted empty-inline">Game over — no bets to build.</p>
          : <BetBuilder home={home} away={away} budget={perMatchBudget} />
      )}

      {tab === 'stake' && (
        <div className="stake-tab slip-tab-content" key="stake">
          {stakeLoading && (
            <div className="stake-skeleton">
              <div className="stake-skel-head">
                <div className="spinner small" />
                <p>Pulling exact payouts from Stake…</p>
              </div>
              <div className="skeleton sk-line" />
              <div className="skeleton sk-line short" />
              <div className="skeleton sk-block" />
            </div>
          )}
          {!stakeLoading && stake && !stake.available && (
            <div className="stake-fallback">
              <span className="fallback-icon" aria-hidden>🔒</span>
              <h5>Live Stake payouts unavailable</h5>
              <p>{stake.reason || "We couldn't reach Stake from this network for this game. Your plan above still uses our best available pricing."}</p>
              <a className="stake-open-btn" href="https://stake.com/sports/soccer" target="_blank" rel="noreferrer">
                Open Stake →
              </a>
            </div>
          )}
          {!stakeLoading && stake?.available && (
            <div className="stake-live">
              <div className="stake-live-head">
                <span className="live-pill stake-live-pill">🟢 LIVE FROM STAKE</span>
              </div>
              <div className="stake-matched">
                Matched on Stake: <strong>{stake.matched_name}</strong>
                <span className="muted"> · {stake.tournament}{stake.status ? ` · ${stake.status}` : ''}</span>
                <div className="muted">
                  Check this is your game before betting.
                  {stake.total_bets > 0 && ` ${stake.total_bets.toLocaleString()} bets · $${stake.total_bet_value_usd?.toLocaleString()} staked.`}
                </div>
              </div>
              <p className="muted">Exact payouts if you put {formatINR(perMatchBudget)} on each:</p>
              {stake.categories.map((cat) => (
                <div key={cat.category} className="options-category">
                  <h5>{cat.category}</h5>
                  <div className="table-wrap">
                    <table className="options-table">
                      <thead><tr><th>Bet</th><th>Payout</th><th>If it wins</th></tr></thead>
                      <tbody>
                        {cat.options.map((o, i) => (
                          <tr key={i}>
                            <td>{o.label}</td>
                            <td className="odds-cell">{o.odds}x</td>
                            <td className="green">{formatINR(o.return_inr)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
              <a className="stake-open-btn" href={stake.stake_url} target="_blank" rel="noreferrer">
                Place on Stake →
              </a>
            </div>
          )}
        </div>
      )}

      {tab === 'factors' && (
        <div className="factors-tab slip-tab-content" key="factors">
          <p className="factors-summary">{factors.summary}</p>
          <ul className="factor-list">
            {factors.top_factors?.map((f, i) => (
              <li key={i}>
                <span className="factor-cat">{f.category}</span>
                <span className="factor-body"><strong>{f.name}</strong> — {f.value}</span>
                <span className="factor-impact">{f.impact}</span>
              </li>
            ))}
          </ul>
          {factors.cross_checks != null && (
            <p className="muted">{factors.cross_checks.toLocaleString()} cross-checks against every market option.</p>
          )}
        </div>
      )}

      {tab === 'players' && (
        <div className="slip-tab-content" key="players">
          <div className="table-wrap">
            <table className="options-table">
              <thead><tr><th>Player</th><th>Payout</th><th>Chance</th><th>Pick?</th></tr></thead>
              <tbody>
                {(categories['Player Props'] || []).map((o, i) => (
                  <tr key={i}><td>{o.label}</td><td className="odds-cell">{o.odds}x</td><td>{o.plain_chance}</td><td>{o.plain_verdict}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          {!(categories['Player Props'] || []).length && (
            <p className="muted empty-inline">No goalscorer markets for this game.</p>
          )}
        </div>
      )}

      {tab === 'all' && (
        <div className="all-options slip-tab-content" key="all">
          {Object.entries(categories).map(([cat, opts]) => (
            <div key={cat} className="options-category">
              <h5>{cat}</h5>
              <div className="table-wrap">
                <table className="options-table">
                  <thead><tr><th>Bet</th><th>Payout</th><th>Pick?</th></tr></thead>
                  <tbody>
                    {opts.map((o, i) => (
                      <tr key={i}><td>{o.label}</td><td className="odds-cell">{o.odds}x</td><td>{o.plain_verdict}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          {!Object.keys(categories).length && (
            <p className="muted empty-inline">No market breakdown available for this game.</p>
          )}
        </div>
      )}
    </div>
  )
}
