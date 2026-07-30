import { useState, useEffect, useRef, useCallback } from 'react'
import { formatINR, useBankroll } from '../context/BankrollContext'
import { fetchStakeOdds, connectStakeSession, fetchErrorMessage, fetchMatchSlipRefresh } from '../api/index'
import BetBuilder from './BetBuilder'
import HitTargetPanel from './HitTargetPanel'

import { IconTarget, IconShield, IconSingle, IconValue, IconParlay } from './Icons'

const STRATEGY_KEYS = [
  { key: 'match_card', label: 'Target', Icon: IconTarget },
  { key: 'min_loss', label: 'Loss-min', Icon: IconShield },
  { key: 'singles_focus', label: 'Single', Icon: IconSingle },
  { key: 'value', label: 'Value', Icon: IconValue },
  { key: 'smart_parlay', label: 'Combos', Icon: IconParlay },
]

function normalizePlans(slip, strategyKey) {
  const withLegs = (items) => (items || []).filter((s) => s?.legs?.length)
  const fromPlans = slip?.strategy_plans?.[strategyKey]
  if (Array.isArray(fromPlans) && fromPlans.length) {
    return withLegs(fromPlans)
  }
  const fromSlips = withLegs(
    (slip?.bet_slips || []).filter((s) => (s.tab_id || s.id) === strategyKey),
  )
  if (fromSlips.length) return fromSlips
  const raw = slip?.strategies?.[strategyKey]
  if (Array.isArray(raw)) return withLegs(raw)
  if (raw?.legs?.length) return [raw]
  return []
}

function clampPlanIndex(index, plans) {
  if (!plans?.length) return 0
  return Math.min(Math.max(0, index), plans.length - 1)
}

function planIsStakeSgm(plan) {
  if (plan?.placement_mode === 'separate_singles' || plan?.slip_type === 'spread_card') {
    return false
  }
  if (plan?.slip_type === 'stake_sgm' || plan?.plan_type === 'stake_combo') {
    return true
  }
  const legs = plan?.legs || []
  if (!legs.length) return false
  const comboLegs = legs.filter(
    (l) => l.role === 'stake_combo' || l.role === 'parlay_leg' || l.market === 'stake_combo',
  )
  if (comboLegs.length === legs.length) return true
  if (comboLegs.length === 1 && legs.length === 1) return true
  return plan?.tab_id === 'smart_parlay' && comboLegs.length > 0 && comboLegs.length === legs.length
}

function planActiveLegs(plan) {
  const legs = plan?.legs || []
  if (!legs.length) return []

  const isSpread = (
    plan?.placement_mode === 'separate_singles'
    || plan?.slip_type === 'spread_card'
    || (plan?.tab_id === 'match_card' && !planIsStakeSgm(plan))
  )
  if (isSpread) {
    const withStake = legs.filter((l) => Number(l.stake_inr) > 0)
    if (withStake.length) return withStake
    return legs.filter((l) => l.label || l.market)
  }

  const isStakeSgm = planIsStakeSgm(plan)
  const active = legs.filter((l) => {
    const stake = Number(l.stake_inr) || 0
    if (stake > 0) return true
    if (l.role === 'parlay_leg' || l.role === 'stake_combo') return true
    const ret = Number(l.return_inr) || 0
    return ret > 0 && Boolean(l.label || l.market)
  })
  if (active.length) return active
  if (isStakeSgm) return legs.slice(0, 1)
  if (Number(plan.total_stake_inr) > 0) {
    return legs.filter((l) => l.label || l.market || l.odds)
  }
  return active
}

function pathTicketCount(plan) {
  if (!plan?.legs?.length) return 0
  return planActiveLegs(plan).length || plan.legs.length
}

function planHitsTarget(plan, targetCashout, budgetInr) {
  if (!plan?.legs?.length) return false
  if ((plan.legs || []).some((l) => l?.hits_target)) return true
  const targetReturn = Number(plan?.target_return_inr || plan?.target_cashout_inr || 0)
  if (targetReturn > 0 && targetCashout > 0) return targetReturn >= targetCashout * 0.95
  const targetProfit = Math.max(0, Number(targetCashout || 0) - Number(budgetInr || 0))
  const statedProfit = Number(plan?.target_profit_inr || 0)
  return statedProfit > 0 && statedProfit >= targetProfit * 0.95
}

const ROLE_META = {
  anchor: { label: 'Insurance' },
  support: { label: 'Insurance' },
  swing: { label: 'Swing' },
  lottery: { label: 'Longshot' },
  target_lotto: { label: 'Profit route' },
  stake_combo: { label: 'Stake combo' },
  main: { label: 'Main' },
  route: { label: 'Profit route' },
  extra: { label: 'Support' },
}

const signedINR = (n) => `${n >= 0 ? '+' : ''}${formatINR(n)}`

function comboSubPicks(legOrLabel, home = '', away = '') {
  if (legOrLabel && typeof legOrLabel === 'object') {
    if (Array.isArray(legOrLabel.combo_parts) && legOrLabel.combo_parts.length > 1) {
      return legOrLabel.combo_parts
    }
    const raw = legOrLabel.selection || legOrLabel.label
    return comboSubPicks(raw, home, away)
  }
  const label = String(legOrLabel || '')
  if (!label) return []
  return label.split(/\s*&\s*/).map((part) => {
    const s = part.replace(/\s*@\s*[\d.]+x\s*$/i, '').trim()
    const low = s.toLowerCase()
    if (low === 'yes') return 'Both teams to score: Yes'
    if (low === 'no') return 'Both teams to score: No'
    if (home && low === home.toLowerCase()) return `${home} to win`
    if (away && low === away.toLowerCase()) return `${away} to win`
    if (low === 'draw') return 'Draw'
    const ou = low.match(/^(over|under)\s+([\d.]+)$/)
    if (ou) return `${ou[1].charAt(0).toUpperCase() + ou[1].slice(1)} ${ou[2]} goals`
    return s
  }).filter(Boolean)
}

function isSgmLeg(leg) {
  return leg?.role === 'stake_combo' || leg?.market === 'stake_combo' || leg?.verified_stake
}

function planWinPct(plan, leg) {
  if (plan?.win_probability_pct != null) return plan.win_probability_pct
  if (plan?.hit_probability_pct != null) return plan.hit_probability_pct
  if (plan?.combined_probability_pct != null) return plan.combined_probability_pct
  if (plan?.hit_probability != null) return Math.round(plan.hit_probability * 1000) / 10
  return leg?.our_probability_pct
}

function buildSlipTickets(strategy, activeLegs, isStakeSgm, home = '', away = '') {
  if (isStakeSgm && activeLegs.length > 0) {
    const leg = activeLegs[0]
    const stake = strategy?.stake_inr || strategy?.total_stake_inr || leg?.stake_inr || 0
    const odds = strategy?.combined_odds || leg?.odds
    return [{
      key: 'sgm-main',
      type: 'stake_sgm',
      label: leg?.label || strategy?.description,
      stake, odds,
      returnInr: leg?.return_inr || Math.round(stake * (odds || 1)),
      payoutText: leg?.payout_text,
      verified: true,
      subPicks: comboSubPicks(leg, home, away),
      hitsTarget: leg?.hits_target,
      breaksEven: leg?.breaks_even,
      soloOutcome: (leg?.hits_target || leg?.breaks_even) ? leg?.solo_outcome_label : '',
      reason: leg?.reason,
    }]
  }
  return activeLegs.map((leg, i) => {
    const stake = Number(leg.stake_inr) || Number(strategy?.total_stake_inr) || 0
    const odds = leg.odds || strategy?.combined_odds
    return {
      key: `leg-${i}`,
      type: isSgmLeg(leg) ? 'stake_sgm' : 'single',
      label: formatTicketLabel(leg, home, away),
      stake,
      odds,
      returnInr: leg.return_inr || Math.round(stake * (odds || 1)),
      payoutText: leg.payout_text,
      verified: leg.odds_source === 'stake' || leg.live_odds || strategy?.verified_stake,
      role: leg.role,
      hitsTarget: leg.hits_target,
      breaksEven: leg.breaks_even,
      soloOutcome: (leg.hits_target || leg.breaks_even) ? leg.solo_outcome_label : '',
      subPicks: isSgmLeg(leg) ? comboSubPicks(leg, home, away) : [],
      reason: leg.reason,
    }
  })
}

function formatTicketLabel(leg, home, away) {
  const raw = (leg?.label || '').trim()
  if (raw && !/^handicap\b/i.test(raw) && !/^\s*handicap\b/i.test(raw)) {
    return raw
  }
  const m = leg?.market || ''
  const sel = (leg?.selection || '').toLowerCase()
  if (m === 'btts' || /both teams to score/i.test(m)) {
    return `Both teams to score: ${sel === 'no' ? 'No' : 'Yes'}`
  }
  if (m === 'over_under_goals' || sel === 'over' || sel === 'under') {
    if (leg?.line != null) {
      const side = sel === 'under' ? 'Under' : 'Over'
      return `${side} ${leg.line} goals`
    }
  }
  if (m === 'asian_handicap' && home && leg?.line != null) {
    const team = sel === 'home' ? home : sel === 'away' ? away : ''
    if (team) {
      const sign = leg.line > 0 ? `+${leg.line}` : String(leg.line)
      const base = `${team} handicap ${sign}`
      return leg?.odds ? `${base} @ ${leg.odds}x` : base
    }
  }
  return raw || 'Bet'
}

function StakeTicketCard({ ticket, index, total, pathMode, home, away }) {
  const isSgm = ticket.type === 'stake_sgm'
  const roleMeta = ticket.role ? ROLE_META[ticket.role] : null
  const showRole = !pathMode && roleMeta && ticket.role !== 'route'
  const hitsTarget = ticket.hitsTarget
  const breaksEven = ticket.breaksEven
  const roleBadge = hitsTarget
    ? 'Profit route'
    : breaksEven
      ? 'Insurance'
      : showRole
        ? roleMeta.label
        : null
  const showSolo = ticket.soloOutcome && (hitsTarget || breaksEven)
  return (
    <div className={`stake-ticket-card ${isSgm ? 'is-sgm' : 'is-single'}${hitsTarget ? ' hits-target' : ''}`}>
      <div className="stake-ticket-head">
        <div className="stake-ticket-head-left">
          <span className="stake-ticket-kind">
            {isSgm ? 'Stake combo' : roleBadge || `Ticket ${index + 1}`}
          </span>
          {ticket.verified && <span className="stake-ticket-verified">Stake price</span>}
        </div>
        {!isSgm && total > 1 && (
          <span className="stake-ticket-index">{index + 1}/{total}</span>
        )}
      </div>
      {ticket.subPicks?.length > 1 ? (
        <ul className="stake-ticket-picks">
          {ticket.subPicks.map((pick) => <li key={pick}>{pick}</li>)}
        </ul>
      ) : (
        <p className="stake-ticket-bet">{formatTicketLabel(ticket, home, away) || ticket.label}</p>
      )}
      {showSolo && (
        <p className="stake-ticket-solo muted">{ticket.soloOutcome}</p>
      )}
      {ticket.payoutText && (
        <p className="stake-ticket-payout muted">{ticket.payoutText}</p>
      )}
      {/* ponytail: no AI narrative under tickets - stats only */}
      <div className="stake-ticket-stats">
        <div className="stake-ticket-stat"><span>Stake</span><strong>{formatINR(ticket.stake || 0)}</strong></div>
        <div className="stake-ticket-stat"><span>Odds</span><strong>{ticket.odds}x</strong></div>
        {ticket.returnInr > 0 && (
          <div className="stake-ticket-stat"><span>Returns</span><strong className="green">{formatINR(ticket.returnInr)}</strong></div>
        )}
      </div>
    </div>
  )
}

function pathLegLabels(opt) {
  if (Array.isArray(opt?.path_legs) && opt.path_legs.length) return opt.path_legs
  return (opt?.legs || []).map((l) => l.label).filter(Boolean)
}

function shortLegLabel(label) {
  if (!label) return ''
  return label
    .replace(/Asian Handicap/gi, 'AH')
    .replace(/Draw No Bet/gi, 'DNB')
    .replace(/Half Time/gi, 'HT')
    .replace(/Anytime Goalscorer/gi, 'GS')
}

function pathOptionTitle(opt, index) {
  if (opt?.path_thesis === 'sgm' || opt?.plan_type === 'stake_combo') {
    const pl = (opt?.path_label || '').replace(/^Stake SGM ·\s*/i, '').trim()
    return pl ? `Stake SGM · ${pl}` : 'Stake SGM'
  }
  const pl = (opt?.path_label || '').replace(/^🎫\s*/, '').trim()
  const legs = pathLegLabels(opt)
  if (pl && / path$/i.test(pl)) return pl
  if (pl && /\balt\b/i.test(pl) && !pl.includes('tickets ·')) return pl.split('·')[0].trim()
  if (pl && !pl.includes('tickets ·') && !pl.includes('-leg spread ·') && !/^\d+ singles?$/.test(pl)) {
    return pl.split('·')[0].trim()
  }
  if (pl && pl.includes('-leg spread ·')) {
    return pl.split('·').slice(1).join('·').trim() || pl
  }
  if (legs.length) {
    const preview = legs.slice(0, 2).map(shortLegLabel).join(', ')
    const suffix = legs.length > 2 ? ` +${legs.length - 2}` : ''
    return preview ? `${preview}${suffix}` : `Path ${index + 1}`
  }
  return opt?.pick_label || `Path ${index + 1}`
}

function pathPickerLabel(opt) {
  return pathOptionTitle(opt, (opt?.option_index || 1) - 1)
}

function planUsesPathMode(plan) {
  const pl = plan?.path_label || ''
  return Boolean(
    plan?.path_thesis
    || pl.includes('tickets ·')
    || pl.includes(' path')
    || pl.toLowerCase().includes(' alt')
    || (plan?.legs?.length >= 3 && !plan?.slip_type?.includes('sgm')),
  )
}

function legSetKey(plan) {
  return (plan?.legs || [])
    .map((l) => `${l.market}|${l.selection}|${l.line}`)
    .sort()
    .join(';')
}

function rejectGarbageCombo(plan) {
  const lbl = (plan?.path_headline || plan?.label || '').toLowerCase()
  if (!lbl.includes('&') || !lbl.includes('to win')) return false
  const parts = lbl.split('&').map((s) => s.replace(/\s+to\s+win/g, '').replace(/\s+goal/g, '').trim())
  return parts.length >= 2 && new Set(parts).size === 1
}

function rejectAntiThesisPlan(plan, home, away) {
  if (!home || !away || !plan) return false
  const h = home.toLowerCase()
  const a = away.toLowerCase()
  const blob = JSON.stringify(plan).toLowerCase()
  // Only drop clear both-sides / correct-score nonsense — not every away pick
  if (blob.includes(`${h}/${a}`) || blob.includes(`${a}/${h}`)) return true
  if (blob.includes(`${h} to win`) && blob.includes(`${a} to win`) && !blob.includes('double')) return true
  return false
}

function pathBucket(plan) {
  const n = plan?.legs?.length || 0
  if (plan?.plan_type === 'stake_combo' || plan?.slip_type === 'stake_sgm' || plan?.path_thesis === 'sgm') {
    return 'sgm'
  }
  if (n <= 1) return 'single'
  if (n <= 3) return 'compact'
  if (n === 4) return 'spread'
  return 'full'
}

function resolveCuratedPicks(slip, home = '', away = '') {
  const curated = slip?.curated_picks
  const targetPlans = normalizePlans(slip, 'match_card')
  let picks = []

  if (curated?.primary) {
    picks = [
      annotatePlan({ ...curated.primary, is_recommended_option: true }, 'Our pick', curated.primary.pick_type || 'Target path'),
      ...(curated.alternatives || []).map((p, i) =>
        annotatePlan(p, p.pick_label || `Alt ${i + 1}`, p.pick_type || 'Also consider'),
      ),
    ].filter(Boolean)
  } else {
    const recKey = slip?.recommended_strategy
    const recId = slip?.recommended_slip_id
    const plans = slip?.strategy_plans?.[recKey] || []
    const match = plans.find((p) => p.option_id === recId) || plans[0]
    if (match?.legs?.length) {
      picks = [annotatePlan(match, 'Our pick', match.slip_type_label || recKey)]
    } else if (slip?.active_strategy?.legs?.length) {
      picks = [annotatePlan(slip.active_strategy, 'Our pick', 'Bet plan')]
    }
  }

  const seen = new Set(picks.map((p) => legSetKey(p) || p.option_id))
  for (const mc of targetPlans) {
    const key = legSetKey(mc) || mc.option_id
    if (seen.has(key)) continue
    picks.push(annotatePlan(mc, pathPickerLabel(mc), 'Target path'))
    seen.add(key)
  }

  for (const key of ['singles_focus', 'min_loss', 'value', 'smart_parlay']) {
    for (const s of normalizePlans(slip, key).slice(0, key === 'singles_focus' ? 2 : 1)) {
      const k = legSetKey(s) || s.option_id
      if (seen.has(k)) continue
      picks.push(annotatePlan(s, pathPickerLabel(s), key === 'singles_focus' ? 'Single bet' : key))
      seen.add(k)
    }
  }

  // Fall back: bet_slips / easy-money / unified singles into viewable plans
  if (!picks.length) {
    for (const bs of (slip?.bet_slips || []).slice(0, 4)) {
      if (!bs?.legs?.length) continue
      picks.push(annotatePlan(bs, bs.pick_label || bs.name || 'Plan', bs.pick_type || 'Bet plan'))
    }
  }
  if (!picks.length) {
    for (const em of (slip?.easy_money || []).slice(0, 3)) {
      const fake = {
        legs: [{ ...em, stake_inr: em.stake_inr || 0, label: em.label }],
        total_stake_inr: em.stake_inr || 0,
        tab_id: 'singles_focus',
        worth_label: em.tag || 'High probability',
        why: em.why || em.reason,
      }
      picks.push(annotatePlan(fake, em.label || 'High probability', 'High probability'))
    }
    for (const u of (slip?.unified_picks || []).slice(0, 2)) {
      const fake = {
        legs: [{ ...u, stake_inr: u.stake_inr || 0, label: u.label }],
        total_stake_inr: u.stake_inr || 0,
        tab_id: 'singles_focus',
        worth_label: u.tag || 'Situational',
        why: u.why,
      }
      const k = legSetKey(fake)
      if (seen.has(k)) continue
      picks.push(annotatePlan(fake, u.label || 'Situational', 'Situational'))
      seen.add(k)
    }
  }

  const filtered = picks.filter(Boolean).filter((p) => !rejectGarbageCombo(p) && !rejectAntiThesisPlan(p, home, away))
  // ponytail: if filters wipe the desk, show unfiltered core plans rather than "No clean edge"
  const out = filtered.length ? filtered : picks.filter(Boolean)
  return sortPathsForDropdown(out)
}

function annotatePlan(plan, label, typeLabel) {
  if (!plan?.legs?.length) return null
  const tab = plan.tab_id || plan.id || ''
  const types = {
    match_card: 'Match card',
    singles_focus: 'Single bet',
    min_loss: 'Loss-min spread',
    value: 'Value play',
    smart_parlay: 'Stake combo',
  }
  return {
    ...plan,
    pick_label: label,
    pick_type: typeLabel || types[tab] || plan.slip_type_label || 'Bet plan',
    pick_reason: plan.pick_reason || plan.why || '',
  }
}

function PlanSlipView({
  plan, slip, targetCashout, stakeLive, stakeLoading, showWhy, onToggleWhy, showTickets = true,
  home = '', away = '', onAddToSlip,
}) {
  if (!plan?.legs?.length) {
    return (
      <div className="skip-note">
        <strong>No plan here.</strong>
        <p className="muted">Nothing cleared our bar for this approach on this match.</p>
      </div>
    )
  }

  const activeLegs = planActiveLegs(plan)
  const isStakeSgm = planIsStakeSgm(plan)
  const slipTickets = buildSlipTickets(plan, activeLegs, isStakeSgm, home, away)
  const pathMode = planUsesPathMode(plan)
  const scenarios = plan.scenarios || slip.payout_scenarios || {}
  const likelyProfit = Number(scenarios?.likely_case?.profit_inr || 0)
  const targetGoal = Number(plan.target_cashout_inr || plan.target_return_inr || targetCashout || 0)
  const targetProfit = Math.max(0, targetGoal - (slip.budget_inr || 0))
  const profitRoute = activeLegs.find((l) => l.hits_target)

  return (
    <>
      <div className="pick-hero">
        <div className="pick-hero-head">
          <span className="pick-type-badge">{plan.pick_type}</span>
          {plan.is_recommended_option && <span className="pick-rec-badge">Recommended</span>}
        </div>
        <h4 className="pick-hero-title">{pathOptionTitle(plan, (plan?.option_index || 1) - 1)}</h4>
        {plan.worth_label && (
          <p className="pick-hero-meta muted">{plan.worth_label}</p>
        )}
        {targetGoal > 0 && (
          <p className="pick-hero-target muted">
            Target profit: {formatINR(Math.max(0, targetGoal - (slip.budget_inr || 0)))}
            {activeLegs.some((l) => l.hits_target)
              ? ' · profit route + insurance'
              : activeLegs.some((l) => l.breaks_even)
                ? ' · break-even insurance'
                : activeLegs.length >= 2
                  ? ' · singles + combo mix'
                  : ''}
          </p>
        )}
        {plan.why && (
          <button type="button" className="pick-why-toggle" onClick={onToggleWhy}>
            {showWhy ? 'Hide math' : 'Ticket math'}
          </button>
        )}
        {showWhy && plan.why && <p className="pick-why-text muted">{plan.why}</p>}
        {typeof onAddToSlip === 'function' && (
          <button
            type="button"
            className="btn-secondary pick-add-slip"
            onClick={() => onAddToSlip(plan, activeLegs)}
          >
            Add to bet slip
          </button>
        )}
      </div>

      <div className={`odds-origin-banner ${stakeLive ? 'origin-stake' : 'origin-book'}`}>
        <span className="origin-dot" aria-hidden />
        {stakeLive ? 'Stake payouts loaded' : stakeLoading ? 'Loading Stake...' : 'Book estimate, verify on Stake'}
      </div>

      <div className="slip-budget-row">
        <div className="budget-tile"><span className="bt-label">Budget</span><strong>{formatINR(slip.budget_inr)}</strong></div>
        <div className="budget-tile"><span className="bt-label">Betting</span><strong>{formatINR(plan.total_stake_inr || 0)}</strong></div>
        <div className="budget-tile keep">
          <span className="bt-label">Kept</span>
          <strong className="green">{formatINR(plan.reserve_inr ?? slip.keep_unbet_inr)}</strong>
        </div>
      </div>

      {profitRoute && targetGoal > 0 && (
        <div className="slip-payout-summary">
          <strong>Profit route hits</strong>
          <span>
            {formatINR(profitRoute.return_inr || profitRoute.stake_inr * profitRoute.odds)} back
            · {formatINR(targetProfit)} profit on {formatINR(slip.budget_inr)} budget
          </span>
        </div>
      )}

      {plan.tab_id === 'min_loss' && plan.reserve_inr != null && (
        <div className="loss-min-banner">
          <strong>Capital preservation</strong>
          <span>
            {formatINR(plan.reserve_inr)} kept ({Math.round((plan.reserve_inr / slip.budget_inr) * 100)}%)
            · {formatINR(plan.total_stake_inr)} across {activeLegs.length} bets
          </span>
        </div>
      )}

      {showTickets && (
        <>
          <h5 className="slip-tickets-head">Tickets ({slipTickets.length})</h5>
          <div className="slip-tickets">
            {slipTickets.map((ticket, i) => (
              <StakeTicketCard
                key={ticket.key}
                ticket={ticket}
                index={i}
                total={slipTickets.length}
                pathMode={pathMode}
                home={home}
                away={away}
              />
            ))}
          </div>
        </>
      )}

      {scenarios?.likely_case && (
        <p className="pick-outcome-line muted">
          Typical outcome: {signedINR(likelyProfit)}
          {scenarios.best_case?.profit_inr != null && (
            <> · best case: {signedINR(scenarios.best_case.profit_inr)}</>
          )}
        </p>
      )}
    </>
  )
}

function PathOptionContent({ opt, index, compact = false }) {
  const legs = pathLegLabels(opt)
  const title = pathOptionTitle(opt, index)
  const n = pathTicketCount(opt)
  const hp = opt.win_probability_pct ?? opt.hit_probability_pct
  const wl = (opt.worth_label || '').split(' · ')[0]
  return (
    <>
      <div className="path-option-head">
        <span className="path-option-title">
          {(opt.is_recommended_option || opt.pick_label === 'Our pick') && '★ '}
          {title}
        </span>
        <div className="path-option-badges">
          {wl && <span className="path-option-meta muted">{wl}</span>}
        </div>
      </div>
      {!compact && legs.length > 0 && (
        <div className="path-option-legs">
          {legs.slice(0, 4).map((l) => (
            <span key={l} className="path-leg-pill">{shortLegLabel(l)}</span>
          ))}
          {legs.length > 4 && (
            <span className="path-leg-pill path-leg-more">+{legs.length - 4}</span>
          )}
        </div>
      )}
      <div className="path-option-foot">
        {n > 0 && <span className="path-option-stat">{n} ticket{n !== 1 ? 's' : ''}</span>}
        {hp != null && <span className="path-option-stat muted">{hp}% any hit</span>}
      </div>
    </>
  )
}

function PathPicker({ plans, index, onSelect, label, id }) {
  const safeIndex = clampPlanIndex(index, plans || [])

  if (!plans?.length) return null

  return (
    <div className="path-picker-inline" id={id}>
      <span className="path-dropdown-label">{label || 'Choose a path'}</span>
      <div className="path-option-list" role="listbox" aria-label={label || 'Paths'}>
        {plans.map((opt, i) => (
          <button
            key={opt.option_id || `path-${i}`}
            type="button"
            role="option"
            aria-selected={i === safeIndex}
            className={`path-option-card${i === safeIndex ? ' active' : ''}`}
            onClick={() => onSelect(i)}
          >
            <PathOptionContent opt={opt} index={i} />
          </button>
        ))}
      </div>
      <p className="muted path-dropdown-hint">Pick a path to see the tickets below.</p>
    </div>
  )
}

function sortPathsForDropdown(plans) {
  const bucketOrder = { compact: 4, spread: 3, sgm: 2, single: 1, full: 0 }
  return [...plans].sort((a, b) => {
    const rank = (p) => {
      const hp = p.hit_probability ?? (p.hit_probability_pct != null ? p.hit_probability_pct / 100 : 0)
      const wl = (p.worth_label || '').toLowerCase()
      const swing = wl.includes('swing') ? 0 : 1
      const top = p.is_recommended_option || p.pick_label === 'Our pick' ? 3 : 0
      const n = p.legs?.length || 0
      const sizeBonus = n >= 2 && n <= 4 ? 1 : 0
      const bucket = bucketOrder[pathBucket(p)] ?? 0
      return top * 100 + swing * 10 + sizeBonus * 5 + bucket * 2 + hp
    }
    return rank(b) - rank(a)
  })
}

function PathDropdown({ plans, index, onSelect, label, id }) {
  return (
    <PathPicker plans={plans} index={index} onSelect={onSelect} label={label} id={id} />
  )
}

function OptionPicker({ plans, index, onSelect, heading, id = 'path-select' }) {
  return (
    <PathDropdown
      plans={plans}
      index={index}
      onSelect={onSelect}
      label={heading || `${plans.length} paths`}
      id={id}
    />
  )
}

export default function MatchSlipPanel({ slip, home, away, fanPrediction, status, score, sport }) {
  const {
    perMatchBudget, updatePerMatchBudget, targetCashout, updateTargetCashout, bettorStyle, addLeg,
  } = useBankroll()
  const [budgetDraft, setBudgetDraft] = useState(String(perMatchBudget))
  const [targetDraft, setTargetDraft] = useState(String(targetCashout))
  const [addedNote, setAddedNote] = useState(null)

  useEffect(() => { setBudgetDraft(String(perMatchBudget)) }, [perMatchBudget])
  useEffect(() => { setTargetDraft(String(targetCashout)) }, [targetCashout])

  const [tab, setTab] = useState('recs')
  const [pickIndex, setPickIndex] = useState(0)
  const [targetIndex, setTargetIndex] = useState(0)
  const [strategyKey, setStrategyKey] = useState('match_card')
  const [optionIndex, setOptionIndex] = useState(0)
  const [stake, setStake] = useState(null)
  const [stakeLoading, setStakeLoading] = useState(false)
  const [stakeConnecting, setStakeConnecting] = useState(false)
  const [showWhy, setShowWhy] = useState(false)
  const [liveSlip, setLiveSlip] = useState(null)
  const [slipRefreshing, setSlipRefreshing] = useState(false)
  const [slipLoadError, setSlipLoadError] = useState(null)
  const matchGenRef = useRef(0)
  const loadSeqRef = useRef(0)
  const stakeSyncedRef = useRef(false)
  const targetStakeSyncedRef = useRef(false)
  const retryRef = useRef(false)

  const loadMatchSlip = useCallback(({ refreshStake = false, isRetry = false } = {}) => {
    if (!home || !away || status === 'completed') return undefined
    const matchGen = matchGenRef.current
    const seq = ++loadSeqRef.current
    setSlipRefreshing(true)
    if (!refreshStake && !isRetry) setSlipLoadError(null)
    return fetchMatchSlipRefresh({
      home, away, budgetInr: perMatchBudget, targetCashoutInr: targetCashout, refreshStake, sport,
      goal: bettorStyle?.goal, risk: bettorStyle?.risk, structure: bettorStyle?.structure,
    })
      .then((data) => {
        if (matchGen !== matchGenRef.current || seq !== loadSeqRef.current) return data
        setLiveSlip(data)
        setSlipLoadError(null)
        retryRef.current = false
        return data
      })
      .catch((err) => {
        if (matchGen !== matchGenRef.current || seq !== loadSeqRef.current) return
        if (!refreshStake) {
          if (!retryRef.current) {
            retryRef.current = true
            loadMatchSlip({ refreshStake: false, isRetry: true })
            return
          }
          setSlipLoadError(fetchErrorMessage(err, 'Could not load bet plans for this match.'))
        }
      })
      .finally(() => {
        if (matchGen === matchGenRef.current && seq === loadSeqRef.current) {
          setSlipRefreshing(false)
        }
      })
  }, [home, away, status, perMatchBudget, targetCashout, sport, bettorStyle])

  const loadStake = () => {
    if (!home || !away || status === 'completed') return
    setStakeLoading(true)
    setStake(null)
    fetchStakeOdds({ home, away, budgetInr: perMatchBudget })
      .then(setStake)
      .catch((err) => setStake({
        available: false,
        reason: fetchErrorMessage(err, 'Stake not connected yet.'),
        categories: [],
      }))
      .finally(() => setStakeLoading(false))
  }

  const connectStake = () => {
    setStakeConnecting(true)
    connectStakeSession()
      .then(() => loadStake())
      .catch((err) => setStake({
        available: false,
        reason: fetchErrorMessage(err, 'Could not open Stake browser.'),
        categories: [],
      }))
      .finally(() => setStakeConnecting(false))
  }

  useEffect(() => {
    matchGenRef.current += 1
    stakeSyncedRef.current = false
    targetStakeSyncedRef.current = false
    retryRef.current = false
    setLiveSlip(null)
    setSlipLoadError(null)
  }, [home, away])

  useEffect(() => {
    if (!home || !away || status === 'completed') return
    if (slip?.strategy_plans || slip?.curated_picks) {
      setLiveSlip(slip)
      return
    }
    loadMatchSlip({ refreshStake: false })
  }, [home, away, status, slip?.match_id, slip?.strategy_plans, slip?.curated_picks, loadMatchSlip])

  useEffect(() => { loadStake() }, [home, away, perMatchBudget, status]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!home || !away || status === 'completed' || tab !== 'target') return
    if (!liveSlip || targetStakeSyncedRef.current) return
    targetStakeSyncedRef.current = true
    loadMatchSlip({ refreshStake: true })
  }, [home, away, status, tab, targetCashout, perMatchBudget, liveSlip, loadMatchSlip])

  // Re-price with Stake only after the fast slip load succeeds so the first request stays visible.
  useEffect(() => {
    if (!stake?.available || tab !== 'recs' || status === 'completed' || !liveSlip || stakeSyncedRef.current) {
      return
    }
    stakeSyncedRef.current = true
    loadMatchSlip({ refreshStake: true })
  }, [stake?.available, tab, home, away, status, liveSlip, loadMatchSlip])

  useEffect(() => { setTargetDraft(String(targetCashout)) }, [targetCashout])

  useEffect(() => {
    setPickIndex(0)
    setTargetIndex(0)
    setOptionIndex(0)
    setShowWhy(false)
    const src = liveSlip || slip
    const rec = src?.recommended_strategy
    const valid = STRATEGY_KEYS.some((s) => s.key === rec)
    if (valid) {
      setStrategyKey(rec)
      return
    }
    const firstWithPlans = STRATEGY_KEYS.find((s) => normalizePlans(src, s.key).length)?.key
    setStrategyKey(firstWithPlans || 'min_loss')
  }, [slip?.match_id, slip?.recommended_slip_id, liveSlip?.match_id, liveSlip?.recommended_slip_id, targetCashout])

  useEffect(() => {
    setPickIndex((i) => clampPlanIndex(i, resolveCuratedPicks(liveSlip || slip, home, away)))
    setTargetIndex((i) => clampPlanIndex(i, normalizePlans(liveSlip || slip, 'match_card')))
    setOptionIndex((i) => clampPlanIndex(i, normalizePlans(liveSlip || slip, strategyKey)))
  }, [liveSlip, slip, strategyKey])

  const activeSlip = liveSlip || slip || null
  const categories = activeSlip?.options_by_category || {}
  const stakeCached = Boolean(activeSlip?.stake_from_cache)
  const stakeLive = Boolean(activeSlip?.stake_priced || (stake?.available && stake?.categories?.length > 0))

  if (!activeSlip && status === 'completed') {
    return (
      <div className="slip-panel">
        <div className="result-banner"><span className="result-label">FINAL</span><strong>{score}</strong></div>
        <p className="muted">Game over. No bets.</p>
      </div>
    )
  }
  if (!activeSlip && status !== 'completed') {
    const failed = Boolean(slipLoadError) && !slipRefreshing
    return (
      <div className="slip-panel">
        <p className="muted">
          {failed ? (slipLoadError || 'Plans unavailable - use Build for Stake-style markets.') : 'Loading picks...'}
        </p>
        {failed && (
          <>
            <button
              type="button"
              className="stake-open-btn secondary"
              onClick={() => loadMatchSlip({ refreshStake: false })}
            >
              Retry plans
            </button>
            <BetBuilder home={home} away={away} budget={perMatchBudget} sport={sport} />
          </>
        )}
      </div>
    )
  }
  if (!activeSlip) return null

  const picks = resolveCuratedPicks(activeSlip, home, away)
  const pickIdx = clampPlanIndex(pickIndex, picks)
  const activePick = picks[pickIdx]

  const planOptions = normalizePlans(activeSlip, strategyKey)
  const planIdx = clampPlanIndex(optionIndex, planOptions)
  const activePlan = planOptions[planIdx]

  const isSkip = activeSlip.verdict === 'SKIP_MATCH' && !activeSlip.recommended_singles?.length
  const showSkipBanner = isSkip || activeSlip.skip_recommended
  const gameProfile = activeSlip.game_profile || {}
  const factors = activeSlip.factor_analysis || {}

  const commitTarget = () => {
    const n = Math.max(100, Math.min(100000, Number(targetDraft) || targetCashout))
    updateTargetCashout(n)
    setTargetDraft(String(n))
    if (status !== 'completed') {
      loadMatchSlip({ refreshStake: tab === 'target' || Boolean(stake?.available) })
    }
  }

  const commitBudget = () => {
    const n = Math.max(1, Math.min(100000, Number(budgetDraft) || perMatchBudget))
    setBudgetDraft(String(n))
    updatePerMatchBudget(n)
    if (status !== 'completed') {
      loadMatchSlip({ refreshStake: Boolean(stake?.available) })
    }
  }

  const addPlanToSlip = (plan, legs) => {
    const eventId = activeSlip?.match_id || `${home}-${away}`
    let added = 0
    for (const leg of (legs || plan?.legs || [])) {
      const odds = Number(leg.odds) || 0
      if (!(odds > 1)) continue
      const label = leg.label || leg.selection || 'Pick'
      const id = `rec-${eventId}-${leg.market || 'mkt'}-${leg.selection || label}-${odds}`
      const ok = addLeg({
        id,
        eventId,
        home,
        away,
        label,
        market: leg.market || 'match_winner',
        marketName: leg.market_label || leg.market || '',
        selection: leg.selection || label,
        odds,
        stake: Number(leg.stake_inr) >= 10 ? Number(leg.stake_inr) : undefined,
        sportKey: sport,
        our_probability: leg.our_probability,
        gem_kind: plan?.pick_type || plan?.tab_id || 'rec',
      })
      if (ok) added += 1
    }
    setAddedNote(added ? `Added ${added} ticket${added === 1 ? '' : 's'} to bet slip` : 'Could not add. Check odds or slip rules.')
    window.setTimeout(() => setAddedNote(null), 2500)
  }

  const TABS = [
    { id: 'recs', label: 'Recs' },
    { id: 'target', label: 'Target' },
    { id: 'plans', label: 'All plans' },
    { id: 'build', label: 'Build' },
    { id: 'stake', label: 'Odds', live: stake?.available },
    { id: 'more', label: 'More' },
  ]

  return (
    <div className="slip-panel">
      <div className="slip-budget-bar">
        <label className="slip-budget-field">
          <span>Avg budget / match</span>
          <input
            type="text"
            inputMode="decimal"
            value={budgetDraft}
            onChange={(e) => setBudgetDraft(e.target.value.replace(/[^\d.]/g, ''))}
            onBlur={commitBudget}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur() } }}
            aria-label="Average match budget"
          />
        </label>
        <p className="muted slip-budget-hint">One number - every plan and stake sizes to this.</p>
      </div>

      {showSkipBanner && tab !== 'target' && (
        <div className={`skip-banner ${isSkip ? 'skip-hard' : 'skip-caution'}`}>
          <strong>{isSkip ? 'Skip this match' : 'Thin edge'}</strong>
          <p>{activeSlip.skip_reason || (isSkip
            ? `Keep all ${formatINR(activeSlip.budget_inr)}. Nothing clears our bar.`
            : 'Edges are soft - size down, or use Target / Build for another path.')}</p>
        </div>
      )}

      {addedNote && <p className="muted recs-empty-note" role="status">{addedNote}</p>}

      {stakeCached && tab !== 'stake' && (
        <p className="muted recs-empty-note">Cached Stake lines. Open Odds to refresh.</p>
      )}

      {!stakeLive && !stakeCached && tab !== 'stake' && picks.length > 0 && (
        <p className="muted recs-empty-note">
          {activeSlip.odds_note || 'Model prices. Verify on Stake before betting.'}
        </p>
      )}

      {!stakeLive && !stakeCached && tab !== 'stake' && !picks.length && (
        <div className="skip-banner skip-caution stake-verify-banner">
          <strong>Verify on Stake</strong>
          <p>No Stake lines loaded yet. Open the Odds tab to connect, then refresh recs.</p>
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
            {t.label}
            {t.live && <span className="tab-live-dot" aria-label="Live"> ●</span>}
          </button>
        ))}
      </div>

      {tab === 'recs' && (
        <div className="slip-content slip-tab-content">
          {activeSlip.easy_money?.length > 0 && (
            <div className="easy-money-box is-lock-tier">
              <h5>High probability</h5>
              <p className="muted situational-sub">p ≥ 62% on core markets · label / odds / chance only.</p>
              <ul className="easy-money-list">
                {activeSlip.easy_money.map((p, i) => (
                  <li key={`easy-${i}`}>
                    <span className="easy-tag">{p.tag || 'High p'}</span>
                    <strong>{p.label}</strong>
                    {p.odds && <span className="easy-odds"> @ {p.odds}</span>}
                    {p.our_probability_pct != null && (
                      <span className="easy-prob"> · {p.our_probability_pct}%</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!activeSlip.easy_money?.length && activeSlip.easy_money_note && (
            <p className="muted recs-empty-note">{activeSlip.easy_money_note}</p>
          )}

          <h5 className="recs-section-head">Our pick</h5>

          {activePick ? (
            <>
              <OptionPicker
                plans={picks}
                index={pickIdx}
                onSelect={(i) => { setPickIndex(i); setShowWhy(false) }}
                heading="Target paths"
                id="recs-path-select"
              />
              <PlanSlipView
                plan={activePick}
                slip={activeSlip}
                targetCashout={targetCashout}
                stakeLive={stakeLive}
                stakeLoading={stakeLoading}
                showWhy={showWhy}
                onToggleWhy={() => setShowWhy(!showWhy)}
                home={home}
                away={away}
                onAddToSlip={addPlanToSlip}
              />
            </>
          ) : (
            <div className="skip-note skip-note-hard">
              <strong>Building priced paths…</strong>
              <p>
                {activeSlip.skip_reason
                  || (slipRefreshing
                    ? 'Loading ESPN/model lines for this match.'
                    : 'Open Build for the full market board, or tap Odds for book estimates.')}
              </p>
              {(activeSlip.easy_money?.length > 0 || activeSlip.unified_picks?.length > 0 || activeSlip.bet_slips?.length > 0) && (
                <p className="muted">High-probability picks and slips are listed above / under All plans.</p>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'target' && (
        <div className="slip-content slip-tab-content">
          {slipRefreshing && (
            <p className="muted recs-empty-note">Loading Stake lines and SGMs...</p>
          )}
          <HitTargetPanel home={home} away={away} status={status} autoLoad sport={sport} />
        </div>
      )}

      {tab === 'plans' && (
        <div className="slip-content slip-tab-content">
          <div className="strategy-picker">
            {STRATEGY_KEYS.map((s) => {
              const count = normalizePlans(activeSlip, s.key).length
              const TabIcon = s.Icon
              return (
                <button
                  key={s.key}
                  type="button"
                  className={strategyKey === s.key ? 'strategy-btn active' : 'strategy-btn'}
                  onClick={() => { setStrategyKey(s.key); setOptionIndex(0) }}
                >
                  <span className="strategy-icon" aria-hidden><TabIcon width={14} height={14} /></span>
                  <span className="strategy-label">{s.label}</span>
                  {count > 0 && <span className="strategy-tag">{count}</span>}
                </button>
              )
            })}
          </div>
          {planOptions.length > 0 ? (
            <>
              <OptionPicker plans={planOptions} index={planIdx} onSelect={setOptionIndex} id="plans-path-select" />
              <PlanSlipView
                plan={activePlan}
                slip={activeSlip}
                targetCashout={targetCashout}
                stakeLive={stakeLive}
                stakeLoading={stakeLoading}
                showWhy={showWhy}
                onToggleWhy={() => setShowWhy(!showWhy)}
                home={home}
                away={away}
                onAddToSlip={addPlanToSlip}
              />
            </>
          ) : (
            <div className="skip-note">
              <strong>No {STRATEGY_KEYS.find((s) => s.key === strategyKey)?.label || 'plan'} options.</strong>
              <p className="muted">Try another tab. Target combos change when you update cashout goal.</p>
            </div>
          )}
        </div>
      )}

      {tab === 'build' && (
        status === 'completed'
          ? <p className="muted empty-inline">Game over.</p>
          : <BetBuilder home={home} away={away} budget={perMatchBudget} sport={sport} />
      )}

      {tab === 'stake' && (
        <div className="stake-tab slip-tab-content">
          {stakeLoading && (
            <div className="stake-skeleton">
              <div className="stake-skel-head"><div className="spinner small" /><p>Pulling Stake payouts...</p></div>
            </div>
          )}
          {!stakeLoading && stake && !stake.available && (
            <div className="stake-fallback">
              <h5>Stake live lines offline</h5>
              <p>
                {stake.reason || 'Cloudflare or geo rules blocked Stake from this host.'}
                {' '}Recs and Build still use ESPN or model prices. Open Stake.com to place.
              </p>
              <button type="button" className="stake-open-btn" onClick={connectStake} disabled={stakeConnecting}>
                {stakeConnecting ? 'Opening...' : 'Reconnect Stake'}
              </button>
              <button type="button" className="stake-open-btn secondary" onClick={loadStake}>Retry</button>
            </div>
          )}
          {!stakeLoading && stake?.available && (
            <div className="stake-live">
              <span className={`live-pill stake-live-pill${['espn_book', 'stake_cache', 'board_espn', 'board_demo', 'demo_books', 'model_fair'].includes(stake.source) || String(stake.source || '').startsWith('board_') ? ' is-book' : ''}`}>
                {stake.source === 'espn_book' || String(stake.source || '').startsWith('board_')
                  ? 'Board estimate'
                  : stake.source === 'demo_books'
                    ? 'Demo books'
                    : stake.source === 'model_fair'
                      ? 'Model estimate'
                      : stake.from_cache ? 'Cached Stake' : 'Live from Stake'}
              </span>
              {stake.note && <p className="muted">{stake.note}</p>}
              <p className="muted">Payouts at {formatINR(perMatchBudget)} stake:</p>
              {stake.categories.map((cat) => (
                <div key={cat.category} className="options-category">
                  <h5>{cat.category}</h5>
                  <div className="table-wrap">
                    <table className="options-table">
                      <thead><tr><th>Bet</th><th>Odds</th><th>Payout</th></tr></thead>
                      <tbody>
                        {cat.options.map((o, i) => (
                          <tr key={i}><td>{o.label}</td><td className="odds-cell">{o.odds}x</td><td className="green">{formatINR(o.return_inr)}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
              <a className="stake-open-btn" href={stake.stake_url} target="_blank" rel="noreferrer">Open on Stake →</a>
            </div>
          )}
        </div>
      )}

      {tab === 'more' && (
        <div className="slip-tab-content more-tab">
          {factors.factors_analyzed > 0 && (
            <div className="factors-tab">
              <ul className="factor-list">
                {factors.top_factors?.slice(0, 8).map((f, i) => (
                  <li key={i}>
                    <span className="factor-cat">{f.category}</span>
                    <span className="factor-body"><strong>{f.name}</strong>: {f.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(categories['Player Props'] || []).length > 0 && (
            <div className="options-category">
              <h5>Scorers</h5>
              <div className="table-wrap">
                <table className="options-table">
                  <thead><tr><th>Player</th><th>Odds</th><th>Chance</th></tr></thead>
                  <tbody>
                    {(categories['Player Props'] || []).slice(0, 12).map((o, i) => (
                      <tr key={i}><td>{o.label}</td><td>{o.odds}x</td><td>{o.plain_chance}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
