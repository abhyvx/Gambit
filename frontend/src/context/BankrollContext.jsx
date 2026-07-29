import { createContext, useContext, useMemo, useState } from 'react'
import { canAddLeg, combinedOdds, slipMode } from '../lib/slipRules'

const DEFAULT_STYLE = {
  goal: 'value',
  risk: 'medium',
  structure: 'spread',
  sports: ['soccer_all', 'soccer_epl', 'basketball_nba'],
}

function loadStyle() {
  try {
    const raw = localStorage.getItem('bettor_style')
    if (!raw) return { ...DEFAULT_STYLE }
    return { ...DEFAULT_STYLE, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_STYLE }
  }
}

function payoutFor(stakeStr, odds) {
  const s = Number(stakeStr)
  const o = Number(odds)
  if (!(s > 0) || !(o > 1)) return null
  return Math.round(s * o)
}

const BankrollContext = createContext()

export function BankrollProvider({ children }) {
  // Used only by Hit Target tab (and API defaults) — not shown in chrome/slip.
  const [perMatchBudget, setPerMatchBudget] = useState(() => {
    const saved = localStorage.getItem('per_match_budget_inr')
    return saved ? Number(saved) : 200
  })
  const [targetCashout, setTargetCashout] = useState(() => {
    const saved = localStorage.getItem('target_cashout_inr')
    return saved ? Number(saved) : 1000
  })
  const [bettorStyle, setBettorStyleState] = useState(loadStyle)

  const [legs, setLegs] = useState([])
  const [legStakes, setLegStakes] = useState({}) // legId -> free-typed string
  const [multiStake, setMultiStakeState] = useState('')
  const [slipMsg, setSlipMsg] = useState(null)

  const updatePerMatchBudget = (val) => {
    const n = Math.max(1, Math.min(100000, Number(val) || 0))
    if (!n) return
    setPerMatchBudget(n)
    localStorage.setItem('per_match_budget_inr', String(n))
  }

  const updateTargetCashout = (val) => {
    const n = Math.max(100, Math.min(100000, Number(val) || 1000))
    setTargetCashout(n)
    localStorage.setItem('target_cashout_inr', String(n))
  }

  const updateBettorStyle = (patch) => {
    setBettorStyleState((prev) => {
      const next = { ...prev, ...patch }
      localStorage.setItem('bettor_style', JSON.stringify(next))
      return next
    })
  }

  const setLegStake = (id, val) => {
    setLegStakes((prev) => ({ ...prev, [id]: String(val ?? '') }))
  }

  const setMultiStake = (val) => {
    setMultiStakeState(String(val ?? ''))
  }

  const addLeg = (leg) => {
    let ok = false
    setLegs((prev) => {
      const check = canAddLeg(prev, leg)
      if (!check.ok) {
        setSlipMsg(check.reason)
        return prev
      }
      ok = true
      setSlipMsg(null)
      const id = leg.id
      // Ignore tiny recommended stubs (e.g. ₹1) — leave Amount blank for the user.
      if (Number(leg.stake) >= 10) {
        setLegStakes((st) => (st[id] != null && st[id] !== '' ? st : { ...st, [id]: String(leg.stake) }))
      }
      return [...prev, leg]
    })
    return ok
  }

  const removeLeg = (id) => {
    setLegs((prev) => prev.filter((l) => l.id !== id))
    setLegStakes((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setSlipMsg(null)
  }

  const clearSlip = () => {
    setLegs([])
    setLegStakes({})
    setMultiStakeState('')
    setSlipMsg(null)
  }

  const setSlip = (payload) => {
    if (!payload) {
      clearSlip()
      return
    }
    const lines = payload.lines || []
    const next = lines.map((line, i) => ({
      id: `legacy-${i}-${line.label}`,
      eventId: payload.eventId || `legacy-${payload.title || 'match'}`,
      home: payload.title || '',
      away: '',
      label: line.label,
      market: line.market || `leg-${i}`,
      selection: line.selection || line.label,
      odds: Number(line.odds) || null,
      sportKey: payload.sportKey,
      league: payload.meta,
    })).filter((l) => l.odds)
    setLegs(next)
    setSlipMsg(null)
  }

  const mode = slipMode(legs)
  const odds = combinedOdds(legs)
  const showMulti = legs.length >= 2

  const singles = useMemo(() => (
    (legs || []).map((leg) => {
      const stake = legStakes[leg.id] ?? ''
      return {
        ...leg,
        stake,
        payout: payoutFor(stake, leg.odds),
      }
    })
  ), [legs, legStakes])

  const multiPayout = showMulti ? payoutFor(multiStake, odds) : null

  const singlesStakeTotal = useMemo(() => (
    singles.reduce((s, leg) => s + (Number(leg.stake) > 0 ? Number(leg.stake) : 0), 0)
  ), [singles])
  const singlesPayoutTotal = useMemo(() => (
    singles.reduce((s, leg) => s + (leg.payout != null ? leg.payout : 0), 0)
  ), [singles])
  const multiStakeNum = Number(multiStake) > 0 ? Number(multiStake) : 0
  const totalStake = singlesStakeTotal + (showMulti ? multiStakeNum : 0)
  const totalPayout = singlesPayoutTotal + (showMulti && multiPayout != null ? multiPayout : 0)

  const slip = legs.length
    ? {
        title: mode === 'sgm' ? 'Same game multi' : mode === 'multi' ? 'Multi' : legs[0].label,
        lines: legs.map((l) => ({ label: l.label, odds: l.odds, win: null })),
        legs,
        mode,
        odds,
        payout: multiPayout,
      }
    : null

  return (
    <BankrollContext.Provider value={{
      perMatchBudget,
      updatePerMatchBudget,
      targetCashout,
      updateTargetCashout,
      bettorStyle,
      updateBettorStyle,
      currency: 'INR',
      bankroll: perMatchBudget,
      updateBankroll: updatePerMatchBudget,
      slip,
      legs,
      slipMode: mode,
      slipOdds: odds,
      slipPayout: multiPayout,
      slipSingles: singles,
      singlesStakeTotal,
      singlesPayoutTotal,
      totalStake,
      totalPayout,
      legStakes,
      setLegStake,
      multiStake,
      setMultiStake,
      showMulti,
      slipMsg,
      setSlipMsg,
      addLeg,
      removeLeg,
      setSlip,
      clearSlip,
      // legacy aliases so older pages don't crash
      slipStake: multiStake,
      updateSlipStake: setMultiStake,
      presets: [],
    }}>
      {children}
    </BankrollContext.Provider>
  )
}

export function useBankroll() {
  return useContext(BankrollContext)
}

export function formatINR(n) {
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}
