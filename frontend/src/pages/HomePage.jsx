import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchEvents, fetchErrorMessage, fetchMarketTop, peekEventsCache } from '../api'
import { SPORT_GROUPS } from '../data/sportBoard'
import {
  FeaturedCard, SportBanner, pickFeatured,
} from '../components/BoardBits'
import BoardBuffer from '../components/BoardBuffer'
import { useEntryReady } from '../components/EntryScreen'
import TopBetTicket from '../components/TopBetTicket'
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

export default function HomePage() {
  const navigate = useNavigate()
  const [pool, setPool] = useState(() => poolFromCaches())
  const [marketBets, setMarketBets] = useState([])
  const [featuredLoading, setFeaturedLoading] = useState(() => poolFromCaches().length === 0)
  const [marketLoading, setMarketLoading] = useState(true)
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
    setMarketLoading(true)
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

    fetchMarketTop(4)
      .then((r) => {
        if (!cancelled) setMarketBets(r.bets || [])
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
    const q = new URLSearchParams({ focus: String(ev.event_id || ev.id) })
    navigate(`/app/sport/${group.id}?${q}`)
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
        {featuredLoading && !featured.length && <BoardBuffer rows={4} label="Loading fixtures…" />}
        {!featured.length && !featuredLoading && <p className="muted">No live or upcoming fixtures right now.</p>}
        {!!featured.length && (
          <div className="featured-track featured-track--four">
            {featured.map((ev) => (
              <FeaturedCard
                key={`${ev.sport_key}-${ev.id}`}
                ev={ev}
                onOpen={openMatch}
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
        <p className="section-sub">Open matches only. Ranked by handle / books - tap a ticket for payout.</p>
        {marketLoading && !marketBets.length && <BoardBuffer rows={3} label="Loading market…" />}
        {!marketLoading && !marketBets.length && (
          <p className="muted">No open priced markets with volume right now.</p>
        )}
        <div className="bet-ticket-list">
          {marketBets.map((b, i) => (
            <TopBetTicket key={`${b.event_id}-${i}`} bet={b} onOpenMatch={openMatch} />
          ))}
        </div>
      </section>
    </div>
  )
}
