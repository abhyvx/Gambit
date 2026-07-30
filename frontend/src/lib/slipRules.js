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

function lineKey(leg) {
  const line = leg?.line
  if (line == null || line === '') {
    // selection may embed the line ("over 2.5")
    const m = String(leg?.selection || '').toLowerCase().match(/(?:over|under)\s+([\d.]+)/)
    return m ? m[1] : ''
  }
  return String(line)
}

/** Normalize selection tokens so "over 2.5" and "over" compare cleanly. */
function selKey(sel) {
  const s = String(sel || '').toLowerCase().trim()
  if (!s) return ''
  if (s === 'over' || s.startsWith('over ')) return 'over'
  if (s === 'under' || s.startsWith('under ')) return 'under'
  if (s === 'yes' || s.endsWith(' - yes') || s.endsWith(': yes')) return 'yes'
  if (s === 'no' || s.endsWith(' - no') || s.endsWith(': no')) return 'no'
  if (s === 'home' || s === '1') return 'home'
  if (s === 'away' || s === '2') return 'away'
  if (s === 'draw' || s === 'x') return 'draw'
  return s
}

function samePick(a, b) {
  return (
    a.market === b.market
    && selKey(a.selection) === selKey(b.selection)
    && lineKey(a) === lineKey(b)
  )
}

/** True opposite on the same market+line (over vs under 2.5, yes vs no BTTS, etc.). */
function conflictsPick(a, b) {
  if (a.market !== b.market) return false
  if (lineKey(a) !== lineKey(b)) return false
  const sa = selKey(a.selection)
  const sb = selKey(b.selection)
  if (!sa || !sb || sa === sb) return false
  const pairs = [
    ['over', 'under'],
    ['yes', 'no'],
    ['home', 'away'],
    ['home', 'draw'],
    ['away', 'draw'],
  ]
  return pairs.some(([x, y]) => (sa === x && sb === y) || (sa === y && sb === x))
}

export function canAddLeg(legs, next) {
  const list = legs || []
  const eid = String(next.eventId)
  const same = list.filter((l) => String(l.eventId) === eid)
  const otherEvents = new Set(list.map((l) => String(l.eventId)).filter((id) => id !== eid))

  if (same.some((l) => samePick(l, next))) {
    return { ok: false, reason: 'Already on your slip' }
  }
  if (same.some((l) => conflictsPick(l, next))) {
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
    id: `${b.event_id}-${b.market || 'match_winner'}-${b.selection}-${b.line ?? ''}`,
    eventId: String(b.event_id),
    home: b.home_team,
    away: b.away_team,
    homeLogo: b.home_logo,
    awayLogo: b.away_logo,
    label: b.label,
    marketName: b.market_name || b.marketName || null,
    market: b.market || 'match_winner',
    selection: b.selection,
    line: b.line ?? null,
    odds: Number(b.decimal_odds),
    sportKey: b.sport_key,
    league: b.league,
    stake: stake || null,
    ticketKind: kind,
    legs: Array.isArray(b.legs) ? b.legs : null,
  }
}
