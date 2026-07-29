const API = '/api'

export async function checkHealth() {
  const r = await fetch(`${API}/health`)
  return r.json()
}

export async function fetchCategories() {
  const r = await fetch(`${API}/categories`)
  return r.json()
}

export async function fetchSports(category = null, featured = false) {
  const params = new URLSearchParams()
  if (category) params.set('category', category)
  if (featured) params.set('featured', 'true')
  const r = await fetch(`${API}/sports?${params}`)
  return r.json()
}

export async function fetchEvents(sport, match = '') {
  const params = new URLSearchParams({ sport })
  if (match) params.set('match', match)
  const r = await fetch(`${API}/events?${params}`)
  return r.json()
}

export async function fetchWorldCup({ matchday, eventId, budgetPerMatchInr = 300, includeCompleted = false, forceRefresh = false } = {}) {
  const params = new URLSearchParams({
    budget_per_match_inr: String(budgetPerMatchInr),
    include_completed: String(includeCompleted),
    force_refresh: String(forceRefresh),
  })
  if (matchday !== undefined && matchday !== null) {
    params.set('matchday', String(matchday))
  }
  if (eventId) params.set('event_id', eventId)
  const r = await fetch(`${API}/worldcup?${params}`, { signal: AbortSignal.timeout(45000) })
  if (!r.ok) throw new Error(`World Cup API failed (${r.status})`)
  return r.json()
}

export async function fetchBetBuilder({ home, away, budgetInr = 300 } = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
  })
  const r = await fetch(`${API}/worldcup/bet-builder?${params}`)
  if (!r.ok) throw new Error(`Bet builder failed (${r.status})`)
  return r.json()
}

export async function refreshStakeOverlay() {
  const r = await fetch(`${API}/stake/refresh`, { method: 'POST', signal: AbortSignal.timeout(90000) })
  if (!r.ok) throw new Error(`Stake refresh failed (${r.status})`)
  return r.json()
}

export async function fetchPortfolioState() {
  const r = await fetch(`${API}/portfolio`)
  if (!r.ok) throw new Error(`Portfolio state failed (${r.status})`)
  return r.json()
}

export async function updatePortfolioPrivacy(payload) {
  const r = await fetch(`${API}/portfolio/privacy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`Portfolio privacy update failed (${r.status})`)
  return r.json()
}

export async function connectPortfolioSession() {
  const r = await fetch(`${API}/portfolio/connect`, { method: 'POST', signal: AbortSignal.timeout(180000) })
  if (!r.ok) throw new Error(`Portfolio connect failed (${r.status})`)
  return r.json()
}

export async function disconnectPortfolioSession() {
  const r = await fetch(`${API}/portfolio/disconnect`, { method: 'POST' })
  if (!r.ok) throw new Error(`Portfolio disconnect failed (${r.status})`)
  return r.json()
}

export async function refreshPortfolioSnapshot() {
  const r = await fetch(`${API}/portfolio/refresh`, { method: 'POST', signal: AbortSignal.timeout(45000) })
  if (!r.ok) {
    let msg = `Portfolio refresh failed (${r.status})`
    try {
      const data = await r.json()
      msg = data.detail || msg
    } catch {
      const text = await r.text()
      if (text) msg = text
    }
    throw new Error(msg)
  }
  return r.json()
}

export async function fetchStakeOdds({ home, away, budgetInr = 300 } = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
  })
  const r = await fetch(`${API}/worldcup/stake-odds?${params}`, { signal: AbortSignal.timeout(90000) })
  if (!r.ok) throw new Error(`Stake odds failed (${r.status})`)
  return r.json()
}

export async function fetchModelReport({ retrain = false } = {}) {
  const params = new URLSearchParams({ retrain: String(retrain) })
  const r = await fetch(`${API}/model/report?${params}`)
  if (!r.ok) throw new Error(`Model report failed (${r.status})`)
  return r.json()
}

export async function fetchModelScorecard() {
  const r = await fetch(`${API}/model/scorecard`)
  if (!r.ok) throw new Error(`Model scorecard failed (${r.status})`)
  return r.json()
}

export async function fetchAnalysis({ sport, match, eventId, bankroll = 2000 } = {}) {
  const params = new URLSearchParams({ sport, bankroll: String(bankroll) })
  if (match) params.set('match', match)
  if (eventId) params.set('event_id', eventId)
  const r = await fetch(`${API}/analyze?${params}`)
  if (!r.ok) throw new Error(`Analysis failed (${r.status})`)
  return r.json()
}
