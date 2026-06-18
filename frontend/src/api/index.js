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
  const r = await fetch(`${API}/worldcup?${params}`)
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

export async function fetchStakeOdds({ home, away, budgetInr = 300 } = {}) {
  const params = new URLSearchParams({
    home,
    away,
    budget_inr: String(budgetInr),
  })
  const r = await fetch(`${API}/worldcup/stake-odds?${params}`)
  if (!r.ok) throw new Error(`Stake odds failed (${r.status})`)
  return r.json()
}

export async function fetchModelReport({ retrain = false } = {}) {
  const params = new URLSearchParams({ retrain: String(retrain) })
  const r = await fetch(`${API}/model/report?${params}`)
  if (!r.ok) throw new Error(`Model report failed (${r.status})`)
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
