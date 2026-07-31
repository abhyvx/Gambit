/** Slip helpers — singles free; multi stake needs one pick per match. */

export function slipMode(legs) {
  if (!legs?.length) return 'empty'
  if (legs.length === 1) return 'single'
  const events = new Set(legs.map((l) => String(l.eventId)))
  if (events.size === 1) return 'sgm'
  if (multiHasSameMatchConflict(legs)) return 'singles'
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

/** True when any match appears more than once — fine for singles, not for a multi stake. */
export function multiHasSameMatchConflict(legs) {
  if (!legs?.length || legs.length < 2) return false
  const counts = {}
  for (const l of legs) {
    const k = String(l.eventId)
    counts[k] = (counts[k] || 0) + 1
  }
  return Object.values(counts).some((n) => n > 1)
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

  if (same.some((l) => samePick(l, next))) {
    return { ok: false, reason: 'Already on your slip' }
  }
  if (same.some((l) => conflictsPick(l, next))) {
    return { ok: false, reason: 'Conflicting pick on this market' }
  }

  // Same-match extras are allowed as separate singles (e.g. two doubles from one game).
  // Multi stake is gated separately when the user types an amount on the multi ticket.
  if (same.length) {
    return { ok: true, mode: list.length ? 'sgm' : 'single' }
  }
  return { ok: true, mode: list.length ? 'multi' : 'single' }
}

export function legFromBet(b, stake) {
  const kind = b.ticket_kind || (
    b.market === 'stake_combo' || b.market === 'hot_double' ? 'combo' : 'single'
  )
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
    odds: Number(b.decimal_odds || b.odds),
    sportKey: b.sport_key,
    league: b.league,
    stake: stake || null,
    ticketKind: kind,
    legs: Array.isArray(b.legs) ? b.legs : null,
  }
}

/** Expand hot doubles / Stake combos into real slip legs (multi or SGM). */
export function legsFromBet(b, stake) {
  const kind = b?.ticket_kind || b?.market
  const isCombo = kind === 'combo'
    || b?.market === 'hot_double'
    || b?.market === 'stake_combo'
  const parts = Array.isArray(b?.legs) ? b.legs.filter(Boolean) : []
  if (!isCombo || parts.length < 2) {
    return [legFromBet(b, stake)]
  }
  return parts.map((part, i) => {
    const src = {
      event_id: part.event_id || part.eventId || b.event_id,
      sport_key: part.sport_key || b.sport_key,
      league: part.league || b.league,
      home_team: part.home_team || b.home_team,
      away_team: part.away_team || b.away_team,
      home_logo: part.home_logo || b.home_logo,
      away_logo: part.away_logo || b.away_logo,
      market: part.market || 'match_winner',
      market_name: part.market_name || part.marketName || 'Match Result',
      selection: part.selection || part.label,
      label: part.label || part.selection,
      line: part.line ?? null,
      decimal_odds: part.decimal_odds || part.odds,
      ticket_kind: 'single',
    }
    const leg = legFromBet(src, i === 0 ? stake : null)
    // Unique ids when two legs share a fused selection string
    leg.id = `${leg.eventId}-${leg.market}-${leg.selection}-${leg.line ?? ''}-${i}`
    return leg
  }).filter((l) => Number(l.odds) > 1 && l.eventId)
}
