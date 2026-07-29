import { createContext, useContext, useMemo, useState } from 'react'
import { canAddLeg, combinedOdds, slipMode } from '../lib/slipRules'
import { recordSlipLegs, settleSlipLeg, confirmPortfolioSlip } from '../api/index'

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
    if (saved) return Number(saved)
    const budget = Number(localStorage.getItem('per_match_budget_inr') || 200)
    return Math.max(300, Math.round(budget * 2.5))
  })
  const [bettorStyle, setBettorStyleState] = useState(loadStyle)

  const [legs, setLegs] = useState([])
  const [legStakes, setLegStakes] = useState({}) // legId -> free-typed string
  const [legResults, setLegResults] = useState({}) // legId -> 'won' | 'lost'
  const [multiStake, setMultiStakeState] = useState('')
  const [slipMsg, setSlipMsg] = useState(null)
  const [slipOpen, setSlipOpenState] = useState(() => {
    try {
      const saved = localStorage.getItem('slip_rail_open')
      // Default closed so the board isn't squeezed by an empty rail
      return saved == null ? false : saved === '1'
    } catch {
      return false
    }
  })

  const setSlipOpen = (next) => {
    const open = typeof next === 'function' ? next(slipOpen) : Boolean(next)
    setSlipOpenState(open)
    try { localStorage.setItem('slip_rail_open', open ? '1' : '0') } catch { /* ignore */ }
  }

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
    const next = String(val ?? '')
    setLegStakes((prev) => ({ ...prev, [id]: next }))
    const leg = (legs || []).find((l) => l.id === id)
    const stake = Number(next)
    if (leg && stake >= 10 && Number(leg.odds) > 1 && !legResults[id]) {
      recordSlipLegs([{ ...leg, stake }]).catch(() => {})
    }
  }

  const setMultiStake = (val) => {
    setMultiStakeState(String(val ?? ''))
  }

  const addLeg = (leg) => {
    let ok = false
    let queued = null
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
      queued = { ...leg, id }
      setSlipOpen(true)
      return [...prev, leg]
    })
    if (ok && queued) {
      // Fire-and-forget: park for craft learning once stake is real
      const stake = Number(queued.stake)
      if (stake >= 10 && Number(queued.odds) > 1) {
        recordSlipLegs([{ ...queued, stake }]).catch(() => {})
      }
    }
    return ok
  }

  const removeLeg = (id) => {
    setLegs((prev) => prev.filter((l) => l.id !== id))
    setLegStakes((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setLegResults((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setSlipMsg(null)
  }

  const clearSlip = () => {
    setLegs([])
    setLegStakes({})
    setLegResults({})
    setMultiStakeState('')
    setSlipMsg(null)
  }

  const settleLeg = async (id, won) => {
    const leg = (legs || []).find((l) => l.id === id)
    if (!leg) return
    const stake = Number(legStakes[id] || leg.stake || 0)
    if (!(stake >= 1) || !(Number(leg.odds) > 1)) {
      setSlipMsg('Set an amount before marking won/lost')
      return
    }
    try {
      // Ensure ticket exists in paper book, then settle into craft weights
      await recordSlipLegs([{ ...leg, stake }])
      await settleSlipLeg({ id, won, sport: leg.sportKey || leg.sport })
      setLegResults((prev) => ({ ...prev, [id]: won ? 'won' : 'lost' }))
      setSlipMsg(won ? 'Logged win. Model updated.' : 'Logged loss. Model updated.')
    } catch (err) {
      setSlipMsg(err?.message || 'Could not update model from this bet')
    }
  }

  const confirmPlaced = async () => {
    const multiOn = (legs || []).length >= 2
    const packed = (legs || []).map((leg) => ({
      ...leg,
      stake: Number(legStakes[leg.id] || 0) || undefined,
      result: legResults[leg.id] || undefined,
      payout: (() => {
        const stake = Number(legStakes[leg.id] || 0)
        const o = Number(leg.odds || 0)
        if (legResults[leg.id] === 'won' && stake > 0 && o > 1) return stake * o
        if (legResults[leg.id] === 'lost') return 0
        return undefined
      })(),
    }))
    try {
      const out = await confirmPortfolioSlip({
        legs: packed,
        multiStake: multiOn ? multiStake : null,
        multiOdds: multiOn ? combinedOdds(legs) : null,
      })
      setSlipMsg((out?.connection?.last_sync_message) || 'Confirmed into your portfolio journal.')
      return out
    } catch (e) {
      setSlipMsg(e?.message || 'Could not confirm placed bets.')
      throw e
    }
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
    setSlipOpen(true)
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
        result: legResults[leg.id] || null,
        payout: payoutFor(stake, leg.odds),
      }
    })
  ), [legs, legStakes, legResults])

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

  // Dynamic rail width: closed / empty / filled
  const slipWidth = !slipOpen ? 0 : (legs.length ? 340 : 280)

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
      settleLeg,
      confirmPlaced,
      slipOpen,
      setSlipOpen,
      slipWidth,
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
