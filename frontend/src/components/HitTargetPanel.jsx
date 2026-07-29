import { useState, useEffect, useCallback } from 'react'
import { formatINR, useBankroll } from '../context/BankrollContext'
import { fetchHitTarget } from '../api/index'

function comboSubPicks(label) {
  if (!label) return []
  return String(label).split(/\s*&\s*/).map((s) => s.trim()).filter(Boolean)
}

const ALLOWED_TYPES = new Set(['match_card', 'coverage', 'stake_combo', 'single', 'split', 'combo'])

function rejectAntiThesisPlan(plan, home, away) {
  if (!home || !away || !plan) return false
  const h = home.toLowerCase()
  const a = away.toLowerCase()
  const blob = JSON.stringify(plan).toLowerCase()
  if (blob.includes(`${h}/${a}`) || blob.includes(`${a}/${h}`)) return true
  if (blob.includes(`${h} to win`) && blob.includes(`${a} to win`) && !blob.includes('double')) return true
  return false
}

function filterPlans(raw, home, away) {
  const base = (raw || []).filter((p) => {
    const t = p?.plan_type
    if (!t || !ALLOWED_TYPES.has(t)) return false
    const lbl = `${p.plan_type_label || ''} ${p.path_headline || ''}`.toLowerCase()
    if (lbl.includes('same-game multi') && t !== 'stake_combo') return false
    if (lbl.includes('sgm') && t !== 'stake_combo' && !lbl.includes('stake combo')) return false
    return true
  })
  const aligned = base.filter((p) => !rejectAntiThesisPlan(p, home, away))
  return (aligned.length ? aligned : base).slice(0, 12)
}

function planMeta(p) {
  const tickets = p.ticket_count ?? (p.legs?.length || 0)
  const wp = p.win_probability_pct ?? p.hit_probability_pct ?? 'n/a'
  const profit = p.best_profit_inr ?? p.target_profit_inr
  const mode = tickets >= 2 ? `${tickets} separate bets` : '1 bet'
  const goal = p.hits_profit_goal ? ' · hits goal' : ''
  return `${mode} · ${wp}% to target · net ${formatINR(profit)}${goal}`
}

function PathTickets({ plan }) {
  return (
    <div className="hit-path-tickets">
      {(plan.tickets || []).map((ticket, ti) => {
        const subPicks = comboSubPicks(ticket.legs?.[0]?.label || plan.label)
        const isSgm = ticket.ticket_type === 'stake_sgm'
        const isParlay = ticket.ticket_type === 'estimated_parlay'
        const stake = ticket.stake_inr || 0
        const odds = ticket.combined_odds || ticket.legs?.[0]?.odds
        const payout = ticket.potential_return_inr || 0
        return (
          <div key={ti} className="hit-ticket stake-ticket-card">
            <div className="stake-ticket-head">
              <span className="stake-ticket-kind">
                {isSgm ? 'Stake combo' : isParlay ? 'Estimated parlay' : ticket.ticket_label}
              </span>
              {stake > 0 && <span className="hit-ticket-stake">{formatINR(stake)}</span>}
            </div>
            {isParlay && (ticket.legs || []).length > 1 ? (
              <ul className="stake-ticket-picks">
                {(ticket.legs || []).map((leg) => <li key={leg.label}>{leg.label}</li>)}
              </ul>
            ) : isSgm && subPicks.length > 1 ? (
              <ul className="stake-ticket-picks">
                {subPicks.map((pick) => <li key={pick}>{pick}</li>)}
              </ul>
            ) : (
              (ticket.legs || []).map((leg, li) => (
                <p key={li} className="stake-ticket-bet">{leg.label}</p>
              ))
            )}
            <div className="stake-ticket-stats">
              <div className="stake-ticket-stat"><span>Stake</span><strong>{formatINR(stake)}</strong></div>
              {odds && <div className="stake-ticket-stat"><span>Odds</span><strong>{odds}x</strong></div>}
              {payout > 0 && (
                <div className="stake-ticket-stat payout">
                  <span>Payout</span><strong>{formatINR(payout)}</strong>
                </div>
              )}
            </div>
            {ticket.placement_note && <p className="hit-ticket-note muted">{ticket.placement_note}</p>}
          </div>
        )
      })}
    </div>
  )
}

export default function HitTargetPanel({ home, away, status, autoLoad = false, sport }) {
  const {
    perMatchBudget, updatePerMatchBudget,
    targetCashout, updateTargetCashout,
    bettorStyle, updateBettorStyle,
  } = useBankroll()
  const [budgetDraft, setBudgetDraft] = useState(String(perMatchBudget))
  const [targetDraft, setTargetDraft] = useState(String(targetCashout))
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [openIdx, setOpenIdx] = useState(0)

  useEffect(() => {
    setTargetDraft(String(targetCashout))
  }, [targetCashout])
  useEffect(() => {
    setBudgetDraft(String(perMatchBudget))
  }, [perMatchBudget])

  const findPath = useCallback((overrideTarget) => {
    if (!home || !away || status === 'completed') return
    const budget = Math.max(1, Math.min(100000, Number(budgetDraft) || perMatchBudget))
    const target = Math.max(
      budget + 1,
      Math.min(100000, Number(overrideTarget ?? targetDraft) || targetCashout),
    )
    setBudgetDraft(String(budget))
    setTargetDraft(String(target))
    updatePerMatchBudget(budget)
    updateTargetCashout(target)
    setLoading(true)
    setError(null)
    fetchHitTarget({
      home, away, budgetInr: budget, targetCashoutInr: target,
      goal: bettorStyle?.goal || 'hit_target', risk: bettorStyle?.risk, structure: bettorStyle?.structure,
      sport,
    })
      .then((res) => {
        // Auto-step down to what the board can actually pay
        const maxPay = Number(res?.max_achievable_inr || 0)
        if (res?.impossible && maxPay > budget + 20 && !overrideTarget) {
          const stepped = Math.max(budget + 50, Math.floor(maxPay * 0.92))
          if (stepped < target) {
            setTargetDraft(String(stepped))
            updateTargetCashout(stepped)
            return fetchHitTarget({
              home, away, budgetInr: budget, targetCashoutInr: stepped,
              goal: 'hit_target', risk: bettorStyle?.risk, structure: bettorStyle?.structure,
              sport,
            }).then((res2) => {
              setData({ ...res2, auto_adjusted_from: target, auto_adjusted_to: stepped })
              setOpenIdx(0)
            })
          }
        }
        setData(res)
        setOpenIdx(0)
      })
      .catch((err) => {
        const msg = err?.name === 'TimeoutError' ? 'Request timed out. Try again in a moment.' : (err.message || 'Failed to find a path')
        setError(msg)
        setData(null)
      })
      .finally(() => setLoading(false))
  }, [home, away, budgetDraft, perMatchBudget, targetDraft, targetCashout, status, updatePerMatchBudget, updateTargetCashout, bettorStyle, sport])

  useEffect(() => {
    if (!autoLoad || !home || !away || status === 'completed') return
    findPath()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoad, home, away, status, perMatchBudget, targetCashout, bettorStyle?.goal, bettorStyle?.risk, bettorStyle?.structure, sport])

  const commitTargetDraft = () => {
    const n = Math.max(100, Math.min(100000, Number(targetDraft) || targetCashout))
    setTargetDraft(String(n))
    updateTargetCashout(n)
  }
  const commitBudgetDraft = () => {
    const n = Math.max(1, Math.min(100000, Number(budgetDraft) || perMatchBudget))
    setBudgetDraft(String(n))
    updatePerMatchBudget(n)
  }

  if (status === 'completed') {
    return <p className="muted empty-inline">Game over. No target paths.</p>
  }

  const plans = filterPlans(data?.plans, home, away)
  const targetNum = Math.max(100, Number(targetDraft) || targetCashout)
  const budgetNum = Math.max(1, Number(budgetDraft) || perMatchBudget)
  const profitGoal = data?.target_profit_inr

  return (
    <div className="hit-target-panel slip-tab-content">
      <p className="hit-target-intro">
        Set budget, style, and cashout here - then find separate tickets that can hit the target.
      </p>

      <div className="hit-style-row">
        <label>
          <span className="bt-label">Goal</span>
          <select
            value={bettorStyle?.goal || 'value'}
            onChange={(e) => updateBettorStyle({ goal: e.target.value })}
          >
            <option value="preserve">Protect bankroll</option>
            <option value="hit_target">Hit cashout</option>
            <option value="value">Find edge</option>
            <option value="fun">Entertainment</option>
          </select>
        </label>
        <label>
          <span className="bt-label">Risk</span>
          <select
            value={bettorStyle?.risk || 'medium'}
            onChange={(e) => updateBettorStyle({ risk: e.target.value })}
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
        <label>
          <span className="bt-label">Structure</span>
          <select
            value={bettorStyle?.structure || 'spread'}
            onChange={(e) => updateBettorStyle({ structure: e.target.value })}
          >
            <option value="singles">One best bet</option>
            <option value="spread">Several singles</option>
            <option value="mixed">Singles + combo</option>
            <option value="parlays">Parlays welcome</option>
          </select>
        </label>
      </div>

      <div className="hit-target-goal-row">
        <div className="hit-target-goal-cell hit-target-goal-input">
          <span className="bt-label">Budget</span>
          <input
            type="text"
            inputMode="decimal"
            value={budgetDraft}
            onChange={(e) => setBudgetDraft(e.target.value.replace(/[^\d.]/g, ''))}
            onBlur={commitBudgetDraft}
          />
        </div>
        <span className="hit-target-arrow" aria-hidden>→</span>
        <div className="hit-target-goal-cell hit-target-goal-input">
          <span className="bt-label">Target cashout</span>
          <input
            type="text"
            inputMode="decimal"
            value={targetDraft}
            onChange={(e) => setTargetDraft(e.target.value.replace(/[^\d.]/g, ''))}
            onBlur={commitTargetDraft}
            onKeyDown={(e) => { if (e.key === 'Enter') findPath() }}
          />
          <small className="muted">{(targetNum / Math.max(budgetNum, 1)).toFixed(1)}×</small>
        </div>
        <button type="button" className="stake-open-btn hit-target-find" onClick={findPath} disabled={loading}>
          {loading ? 'Searching…' : 'Find paths'}
        </button>
      </div>

      {!loading && !error && !data && (
        <p className="muted hit-target-idle">Set budget + target, then tap Find paths.</p>
      )}

      {loading && (
        <div className="hit-target-loading">
          <div className="spinner small" />
          <p>Searching routes to {formatINR(targetNum)}…</p>
        </div>
      )}

      {!loading && error && (
        <div className="skip-note">
          <strong>Could not find a path</strong>
          <p>{error}</p>
          <button type="button" className="stake-open-btn" onClick={findPath}>Retry</button>
        </div>
      )}

      {!loading && !error && data?.impossible && (
        <div className="skip-banner skip-caution">
          <strong>Can&apos;t reach {formatINR(targetNum)} with ₹{budgetNum} budget</strong>
          <p>{data.impossible_reason || data.summary || 'Odds on this board are too short for that multiple.'}</p>
          {data.max_achievable_inr != null && (
            <p className="muted">Max payout on priced markets: {formatINR(data.max_achievable_inr)}</p>
          )}
          {Number(data.max_achievable_inr) > budgetNum + 20 && (
            <button
              type="button"
              className="stake-open-btn"
              onClick={() => findPath(Math.floor(Number(data.max_achievable_inr) * 0.92))}
            >
              Find paths to {formatINR(Math.floor(Number(data.max_achievable_inr) * 0.92))}
            </button>
          )}
        </div>
      )}

      {!loading && !error && data?.auto_adjusted_from && plans.length > 0 && (
        <p className="muted hit-target-idle">
          Target stepped from {formatINR(data.auto_adjusted_from)} → {formatINR(data.auto_adjusted_to)} so a path exists on this board.
        </p>
      )}

      {!loading && !error && plans.length > 0 && !data?.impossible && (
        <div className="hit-path-list">
          {plans.map((p, i) => {
            const open = openIdx === i
            const profit = p.best_profit_inr ?? p.target_profit_inr
            return (
              <article key={p.option_id || i} className={`hit-path-row ${open ? 'is-open' : ''}`}>
                <button
                  type="button"
                  className="hit-path-summary"
                  onClick={() => setOpenIdx(open ? -1 : i)}
                  aria-expanded={open}
                >
                  <span className="hit-path-rank">#{p.rank || i + 1}</span>
                  <span className="hit-path-title">{p.path_headline || p.description}</span>
                  <span className="hit-path-meta muted">{planMeta(p)}</span>
                </button>
                {open && (
                  <div className="hit-path-detail">
                    {p.why && <p className="hit-path-why muted">{p.why}</p>}
                    <div className="hit-path-stats">
                      <span>Stake <strong>{formatINR(p.total_stake_inr)}</strong></span>
                      <span>Reach target <strong>{p.win_probability_pct ?? p.hit_probability_pct}%</strong></span>
                      <span>Net <strong>{formatINR(profit)}</strong></span>
                      {profitGoal != null && <span>Goal <strong>{formatINR(profitGoal)}</strong></span>}
                    </div>
                    <PathTickets plan={p} />
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      {!loading && !error && data && !data.impossible && plans.length === 0 && (
        <div className="skip-note">
          <strong>No path found</strong>
          <p>Try a lower target or raise the budget above.</p>
        </div>
      )}
    </div>
  )
}
