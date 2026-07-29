/** Slip helpers — Stake multi (1 pick / event) + SGM (same event). */

export function slipMode(legs) {
  if (!legs?.length) return 'empty'
  if (legs.length === 1) return 'single'
  const events = new Set(legs.map((l) => String(l.eventId)))
  if (events.size === 1) return 'sgm'
  return 'multi'
}

export function combinedOdds(legs) {
  if (!legs?.length) return null
  let p = 1
  for (const l of legs) {
    const o = Number(l.odds)
    if (!o || o <= 1) return null
    p *= o
  }
  return Math.round(p * 100) / 100
}

export function canAddLeg(legs, next) {
  const list = legs || []
  const eid = String(next.eventId)
  const same = list.filter((l) => String(l.eventId) === eid)
  const otherEvents = new Set(list.map((l) => String(l.eventId)).filter((id) => id !== eid))

  if (same.some((l) => l.market === next.market && l.selection === next.selection)) {
    return { ok: false, reason: 'Already on your slip' }
  }
  if (same.some((l) => l.market === next.market && l.selection !== next.selection)) {
    return { ok: false, reason: 'Conflicting pick on this market' }
  }

  if (same.length) {
    // SGM only when slip is same-game (no other events)
    if (otherEvents.size) {
      return {
        ok: false,
        reason: 'Multi bets allow one pick per match. Clear other matches to build an SGM.',
      }
    }
    return { ok: true, mode: 'sgm' }
  }

  // New event while slip is already an SGM
  const byEvent = {}
  for (const l of list) {
    const k = String(l.eventId)
    byEvent[k] = (byEvent[k] || 0) + 1
  }
  if (Object.values(byEvent).some((n) => n > 1)) {
    return {
      ok: false,
      reason: 'SGM is same-game only. Clear the slip to add another match.',
    }
  }
  return { ok: true, mode: list.length ? 'multi' : 'single' }
}

export function legFromBet(b, stake) {
  const kind = b.ticket_kind || (b.market === 'stake_combo' ? 'combo' : 'single')
  return {
    id: `${b.event_id}-${b.market || 'match_winner'}-${b.selection}`,
    eventId: String(b.event_id),
    home: b.home_team,
    away: b.away_team,
    homeLogo: b.home_logo,
    awayLogo: b.away_logo,
    label: b.label,
    marketName: b.market_name || b.marketName || null,
    market: b.market || 'match_winner',
    selection: b.selection,
    odds: Number(b.decimal_odds),
    sportKey: b.sport_key,
    league: b.league,
    stake: stake || null,
    ticketKind: kind,
    legs: Array.isArray(b.legs) ? b.legs : null,
  }
}
