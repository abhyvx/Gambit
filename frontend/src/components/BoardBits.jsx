import TeamLogo from './TeamLogo'

export function fmtKickoff(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function pct(x) {
  if (x == null) return '-'
  const n = Number(x)
  if (n <= 1) return `${Math.round(n * 100)}%`
  return `${Math.round(n)}%`
}

export function fmtOdds(n) {
  if (n == null || !Number(n)) return null
  return Number(n).toFixed(2)
}

export function hotScore(ev) {
  // Popular upcoming > "next kickoff". Live still wins, then handle/books/league heat.
  let s = 0
  if (ev.status === 'live') s += 1400
  if (ev.status === 'upcoming') s += 300
  if (ev.status === 'completed') s -= 500

  const handle = Number(ev.handle_usd || ev.extra?.handle_usd || 0)
  if (handle > 0) s += Math.min(400, Math.log10(handle + 10) * 80)
  const bettors = Number(ev.bettors || ev.extra?.bettors || ev.extra?.total_bettors || 0)
  if (bettors > 0) s += Math.min(250, Math.log10(bettors + 10) * 55)
  const books = Number(ev.books || ev.bookmakers?.length || ev.extra?.books || 0)
  if (books > 0) s += Math.min(120, books * 18)

  if (ev.odds?.home && ev.odds?.away) s += 120
  else if (ev.odds?.home || ev.odds?.away) s += 40
  if ((ev.odds_source || ev.source || '').includes('stake')) s += 110

  const league = String(ev.league || ev.sport_title || '').toLowerCase()
  if (/premier|champions|la liga|bundesliga|serie a|nba|wnba|world cup|icc|ipl|t20/.test(league)) s += 90
  if (/friendly|club friendly|reserve|u21|u-21/.test(league)) s -= 120

  if (ev.kickoff) {
    const mins = (new Date(ev.kickoff) - Date.now()) / 60000
    // Soft time bias: prefer today/tomorrow popular cards, not "next in 12 min".
    if (mins >= -15 && mins < 180) s += 35
    else if (mins >= 0 && mins < 36 * 60) s += 55
    else if (mins >= 0 && mins < 72 * 60) s += 25
    else if (mins > 7 * 24 * 60) s -= 40
  }
  return s
}

export function pickFeatured(rows, n = 8) {
  const open = [...rows].filter((r) => r.status === 'live' || r.status === 'upcoming')
  open.sort((a, b) => hotScore(b) - hotScore(a))
  // Balance sports so Home isn't soccer-only / "next kickoff" only
  const buckets = { soccer: [], basketball: [], cricket: [], other: [] }
  for (const ev of open) {
    const sk = String(ev.sport_key || '')
    if (sk.startsWith('basket')) buckets.basketball.push(ev)
    else if (sk.startsWith('cricket')) buckets.cricket.push(ev)
    else if (sk.startsWith('soccer') || !sk) buckets.soccer.push(ev)
    else buckets.other.push(ev)
  }
  const out = []
  const seen = new Set()
  const per = Math.max(1, Math.ceil(n / 3))
  for (const key of ['soccer', 'basketball', 'cricket', 'other']) {
    for (const ev of buckets[key].slice(0, per)) {
      const id = `${ev.sport_key}-${ev.id}`
      if (seen.has(id)) continue
      seen.add(id)
      out.push(ev)
      if (out.length >= n) return out
    }
  }
  for (const ev of open) {
    const id = `${ev.sport_key}-${ev.id}`
    if (seen.has(id)) continue
    seen.add(id)
    out.push(ev)
    if (out.length >= n) break
  }
  return out
}

export function OddsBtn({ label, value, stake, onClick }) {
  const v = fmtOdds(value)
  return (
    <button
      type="button"
      className={`odds-btn ${v ? '' : 'is-empty'} ${stake ? 'is-stake' : ''}`.trim()}
      disabled={!v}
      onClick={(e) => {
        e.stopPropagation()
        if (v && onClick) onClick(e)
      }}
    >
      <span className="odds-btn-label">{label}{stake ? ' · S' : ''}</span>
      <span className="odds-btn-price">{v || '-'}</span>
    </button>
  )
}

export function FeaturedCard({ ev, onOpen, showDraw = true, sport = '', onAddOdds }) {
  const odds = ev.odds || {}
  const priced = odds.home && odds.away
  const parts = (ev.status === 'live' || ev.status === 'completed')
    ? (() => {
        const h = ev.home_score_display ?? (ev.home_score != null ? String(ev.home_score) : null)
        const a = ev.away_score_display ?? (ev.away_score != null ? String(ev.away_score) : null)
        if (h != null || a != null) return { home: h ?? 'n/a', away: a ?? 'n/a' }
        return null
      })()
    : null
  return (
    <button
      type="button"
      className={`featured-card ${ev.status === 'live' ? 'is-live' : ''}`}
      onClick={() => onOpen?.(ev)}
    >
      {ev.status === 'live' ? (
        <span className="live-tag">{ev.status_detail ? `LIVE · ${ev.status_detail}` : 'LIVE'}</span>
      ) : (
        <span className="ft-tag">UP</span>
      )}
      <div className="featured-teams">
        <TeamLogo name={ev.home_team} src={ev.home_logo} size={22} preferFlag={!ev.home_logo} sport={sport} />
        <span>{ev.home_team}</span>
        {parts && <strong className="fixture-score">{parts.home}</strong>}
      </div>
      <div className="featured-teams">
        <TeamLogo name={ev.away_team} src={ev.away_logo} size={22} preferFlag={!ev.away_logo} sport={sport} />
        <span>{ev.away_team}</span>
        {parts && <strong className="fixture-score">{parts.away}</strong>}
      </div>
      {priced ? (
        <div
          className="featured-odds"
          aria-label="Match odds — click to add"
          onClick={(e) => e.stopPropagation()}
        >
          <OddsBtn
            label="1"
            value={odds.home}
            onClick={() => onAddOdds?.(ev, 'home')}
          />
          {showDraw && odds.draw ? (
            <OddsBtn label="X" value={odds.draw} onClick={() => onAddOdds?.(ev, 'draw')} />
          ) : null}
          <OddsBtn
            label="2"
            value={odds.away}
            onClick={() => onAddOdds?.(ev, 'away')}
          />
        </div>
      ) : (
        <small>{fmtKickoff(ev.kickoff) || ev.league}</small>
      )}
    </button>
  )
}

export function SportBanner({ sport, onClick }) {
  const style = {
    ...(sport.image ? { '--banner-img': `url(${sport.image})` } : {}),
    ...(sport.imagePos ? { '--banner-pos': sport.imagePos } : {}),
  }
  return (
    <button
      type="button"
      className={`sport-banner-v sport-banner-v--${sport.id}`}
      onClick={onClick}
      aria-label={sport.name}
      style={Object.keys(style).length ? style : undefined}
    >
      <span className="sport-banner-v-photo" aria-hidden />
      <span className="sport-banner-v-shade" aria-hidden />
      <span className="sport-banner-v-center">
        <strong>{sport.name}</strong>
        <small>{sport.blurb}</small>
      </span>
    </button>
  )
}

export function LeagueBanner({ league, active, onClick }) {
  const hasPhoto = Boolean(league.image)
  return (
    <button
      type="button"
      className={`league-banner-v ${active ? 'active' : ''} ${league.top === false ? 'is-other' : ''} ${hasPhoto ? '' : 'no-photo'}`}
      style={{
        '--league-accent': league.accent || '#1a2c38',
        ...(hasPhoto ? { '--banner-img': `url(${league.image})` } : {}),
        ...(league.imagePos ? { '--banner-pos': league.imagePos } : {}),
      }}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onClick?.(e)
      }}
      aria-pressed={active}
      aria-label={league.name}
    >
      {hasPhoto && <span className="league-banner-v-photo" aria-hidden />}
      {hasPhoto && <span className="league-banner-v-shade" aria-hidden />}
      <span className="league-banner-v-center">
        {league.logo ? (
          <img src={league.logo} alt="" className="league-banner-v-logo" loading="lazy" />
        ) : null}
        <strong>{league.name}</strong>
        {active && <small className="league-banner-v-on">Selected</small>}
      </span>
    </button>
  )
}

/** Board favorites → TopBetTicket shape, ranked by popularity not soonest kickoff. */
export function marketPicksFromRows(rows, n = 8) {
  const picks = []
  for (const ev of rows) {
    if (ev.status !== 'live' && ev.status !== 'upcoming') continue
    const o = ev.odds || {}
    const sides = [
      { selection: 'home', label: `${ev.home_team} to win`, price: o.home },
      { selection: 'draw', label: 'Draw', price: o.draw },
      { selection: 'away', label: `${ev.away_team} to win`, price: o.away },
    ].filter((s) => s.price && Number(s.price) >= 1.28 && Number(s.price) <= 6.5)
    if (!sides.length) continue
    // Prefer value-band favorite, not 1.05 juice
    sides.sort((a, b) => {
      const band = (p) => (Number(p) >= 1.5 && Number(p) <= 3.2 ? 0 : 1)
      return band(a.price) - band(b.price) || Number(a.price) - Number(b.price)
    })
    const best = sides[0]
    picks.push({
      event_id: ev.id,
      home_team: ev.home_team,
      away_team: ev.away_team,
      home_logo: ev.home_logo,
      away_logo: ev.away_logo,
      sport_key: ev.sport_key,
      league: ev.league || ev.sport_title,
      label: best.label,
      selection: best.selection,
      market: 'match_winner',
      market_name: 'Match Result',
      decimal_odds: Number(best.price),
      status: ev.status,
      handle_usd: ev.handle_usd || ev.extra?.handle_usd,
      bettors: ev.bettors || ev.extra?.bettors,
      books: ev.bookmaker_count || ev.books,
      match: `${ev.home_team} vs ${ev.away_team}`,
      eventId: ev.id,
      odds: Number(best.price),
      raw: ev,
      source: ev.odds_source || ev.source || 'espn_books',
      marketPick: true,
      ticket_kind: 'single',
      _hot: hotScore(ev) + (Number(best.price) >= 1.5 && Number(best.price) <= 3.2 ? 40 : 0),
    })
  }
  picks.sort((a, b) => (b._hot || 0) - (a._hot || 0))
  return picks.slice(0, n)
}

export function LoadMore({ left, onClick }) {
  if (left <= 0) return null
  return (
    <button type="button" className="btn-secondary load-more" onClick={onClick}>
      Load more ({left} left)
    </button>
  )
}
