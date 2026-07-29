import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchEvents, fetchErrorMessage, fetchMarketTop, peekEventsCache, peekMarketTop } from '../api'
import { SPORT_GROUPS, leagueTabForEvent } from '../data/sportBoard'
import {
  FeaturedCard, SportBanner, pickFeatured,
} from '../components/BoardBits'
import BoardBuffer from '../components/BoardBuffer'
import { useEntryReady } from '../components/EntryScreen'
import TopBetTicket from '../components/TopBetTicket'
import { useBankroll } from '../context/BankrollContext'
import { legFromBet } from '../lib/slipRules'
import './pages.css'

function normalizeEvent(e, sportKey) {
  return { ...e, sport_key: sportKey, odds: e.odds || {} }
}

function poolFromCaches() {
  const rows = []
  const seen = new Set()
  for (const sport of ['soccer_epl', 'soccer_all', 'basketball_all', 'cricket_all']) {
    const cached = peekEventsCache(sport)
    if (!cached?.events) continue
    for (const e of cached.events) {
      const row = normalizeEvent(e, sport)
      const k = `${row.sport_key}-${row.id}`
      if (seen.has(k)) continue
      seen.add(k)
      rows.push(row)
    }
  }
  return rows
}

/** Stamp Stake handle/bettors onto board rows so Top matches rank by popularity. */
function enrichWithPopularity(rows, bets) {
  const byId = new Map()
  for (const b of bets || []) {
    if (b.event_id == null) continue
    const cur = byId.get(b.event_id) || {}
    byId.set(b.event_id, {
      handle_usd: Math.max(Number(cur.handle_usd) || 0, Number(b.handle_usd) || 0) || undefined,
      bettors: Math.max(Number(cur.bettors) || 0, Number(b.bettors) || 0) || undefined,
      books: Math.max(Number(cur.books) || 0, Number(b.books) || 0) || undefined,
    })
  }
  if (!byId.size) return rows
  return rows.map((ev) => {
    const pop = byId.get(ev.id)
    if (!pop) return ev
    return { ...ev, ...pop, extra: { ...(ev.extra || {}), ...pop } }
  })
}

export default function HomePage() {
  const navigate = useNavigate()
  const { addLeg, setSlipOpen } = useBankroll()
  const [pool, setPool] = useState(() => poolFromCaches())
  const [marketBets, setMarketBets] = useState(() => peekMarketTop(8)?.bets || [])
  const [featuredLoading, setFeaturedLoading] = useState(() => poolFromCaches().length === 0)
  const [marketLoading, setMarketLoading] = useState(() => !(peekMarketTop(8)?.bets?.length))
  const [err, setErr] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  useEntryReady(!featuredLoading)

  useEffect(() => {
    let cancelled = false
    const warm = poolFromCaches()
    if (warm.length) {
      setPool(warm)
      setFeaturedLoading(false)
    } else {
      setFeaturedLoading(true)
    }
    const warmMarket = peekMarketTop(8)
    if (warmMarket?.bets?.length) {
      setMarketBets(warmMarket.bets)
      setMarketLoading(false)
    } else {
      setMarketLoading(true)
    }
    setErr(null)

    fetchEvents('soccer_epl')
      .then((r) => {
        if (cancelled) return
        setPool((prev) => {
          const rows = [...prev]
          const seen = new Set(rows.map((e) => `${e.sport_key}-${e.id}`))
          for (const e of (r.events || []).map((ev) => normalizeEvent(ev, 'soccer_epl'))) {
            const k = `${e.sport_key}-${e.id}`
            if (!seen.has(k)) {
              seen.add(k)
              rows.push(e)
            }
          }
          return rows.length ? rows : (r.events || []).map((e) => normalizeEvent(e, 'soccer_epl'))
        })
      })
      .catch((e) => {
        if (!cancelled && !poolFromCaches().length) setErr(fetchErrorMessage(e, 'Could not load boards'))
      })
      .finally(() => { if (!cancelled) setFeaturedLoading(false) })

    Promise.allSettled([
      fetchEvents('soccer_all'),
      fetchEvents('basketball_all'),
      fetchEvents('cricket_all'),
    ]).then((results) => {
      if (cancelled) return
      setPool((prev) => {
        const rows = [...prev]
        const seen = new Set(rows.map((e) => `${e.sport_key}-${e.id}`))
        for (const res of results) {
          if (res.status !== 'fulfilled') continue
          const sport = res.value.sport || 'soccer_all'
          for (const e of res.value.events || []) {
            const row = normalizeEvent(e, sport)
            const k = `${row.sport_key}-${row.id}`
            if (!seen.has(k)) {
              seen.add(k)
              rows.push(row)
            }
          }
        }
        return rows
      })
    })

    fetchMarketTop(8)
      .then((r) => {
        if (cancelled) return
        const bets = r.bets || []
        setMarketBets(bets)
        setPool((prev) => enrichWithPopularity(prev, bets))
      })
      .catch(() => { if (!cancelled) setMarketBets([]) })
      .finally(() => { if (!cancelled) setMarketLoading(false) })

    return () => { cancelled = true }
  }, [reloadKey])

  const featured = useMemo(() => pickFeatured(pool, 4), [pool])
  const openCount = useMemo(
    () => pool.filter((r) => r.status === 'live' || r.status === 'upcoming').length,
    [pool],
  )

  const openMatch = (ev) => {
    const group = SPORT_GROUPS.find((g) => {
      if (ev.sport_key?.startsWith('basketball')) return g.id === 'basketball'
      if (ev.sport_key?.startsWith('cricket')) return g.id === 'cricket'
      return g.id === 'soccer'
    }) || SPORT_GROUPS[0]
    const league = leagueTabForEvent(ev) || ev.league_key || ev.sport_key
    const focus = String(ev.event_id || ev.id || '')
    const q = new URLSearchParams()
    if (focus) q.set('focus', focus)
    if (league) q.set('league', String(league))
    if (ev.home_team) q.set('home', String(ev.home_team))
    if (ev.away_team) q.set('away', String(ev.away_team))
    navigate(`/app/sport/${group.id}?${q}`)
  }

  const addFeaturedOdds = (ev, side) => {
    const o = ev.odds || {}
    const price = o[side]
    if (!price) return
    const label = side === 'home' ? `${ev.home_team} to win`
      : side === 'away' ? `${ev.away_team} to win` : 'Draw'
    const ok = addLeg(legFromBet({
      event_id: ev.id,
      home_team: ev.home_team,
      away_team: ev.away_team,
      home_logo: ev.home_logo,
      away_logo: ev.away_logo,
      sport_key: ev.sport_key,
      league: ev.league,
      market: 'match_winner',
      market_name: 'Match Result',
      selection: side,
      label,
      decimal_odds: price,
    }, null))
    if (ok) setSlipOpen?.(true)
  }

  return (
    <div className="home-board">
      <header className="board-top">
        <div>
          <h1>Home</h1>
          <p className="muted">
            {featuredLoading ? 'Scraping boards…' : `${openCount} live / upcoming`}
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => setReloadKey((k) => k + 1)} disabled={featuredLoading}>
          Refresh
        </button>
      </header>

      {err && <p className="muted" role="alert">{err}</p>}

      <section className="featured-rail">
        <div className="section-label">Top matches</div>
        <p className="section-sub">Most popular across soccer, basketball, and cricket.</p>
        {featuredLoading && !featured.length && <BoardBuffer rows={4} label="Loading fixtures…" />}
        {!featured.length && !featuredLoading && <p className="muted">No live or upcoming fixtures right now.</p>}
        {!!featured.length && (
          <div className="featured-track featured-track--four">
            {featured.map((ev) => (
              <FeaturedCard
                key={`${ev.sport_key}-${ev.id}`}
                ev={ev}
                onOpen={openMatch}
                onAddOdds={addFeaturedOdds}
                showDraw={!ev.sport_key?.startsWith('basketball')}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="section-label">Sports</div>
        <div className="sport-banner-row">
          {SPORT_GROUPS.map((g) => (
            <SportBanner key={g.id} sport={g} onClick={() => navigate(`/app/sport/${g.id}`)} />
          ))}
        </div>
      </section>

      <section className="top-picks-block">
        <div className="section-label">Top bets</div>
        <p className="section-sub">Hot singles and combos. Amount is optional.</p>
        {marketLoading && !marketBets.length && <BoardBuffer rows={3} label="Loading market…" />}
        {!marketLoading && !marketBets.length && (
          <p className="muted">No open priced markets with volume right now.</p>
        )}
        <div className="bet-ticket-list">
          {marketBets.map((b, i) => (
            <TopBetTicket key={`${b.event_id}-${b.market}-${b.selection}-${i}`} bet={b} onOpenMatch={openMatch} />
          ))}
        </div>
      </section>
    </div>
  )
}
