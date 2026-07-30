/** ponytail: slip rule self-check — fails if multi/SGM gates regress. */
import { canAddLeg, slipMode, combinedOdds } from '../lib/slipRules.js'

const a = { eventId: '1', market: 'mw', selection: 'home', odds: 2 }
const b = { eventId: '1', market: 'btts', selection: 'yes', odds: 1.8 }
const c = { eventId: '2', market: 'mw', selection: 'home', odds: 1.5 }
const o15 = { eventId: '1', market: 'over_under_goals', selection: 'over', line: 1.5, odds: 1.4 }
const o25 = { eventId: '1', market: 'over_under_goals', selection: 'over', line: 2.5, odds: 1.9 }
const u25 = { eventId: '1', market: 'over_under_goals', selection: 'under', line: 2.5, odds: 1.9 }

console.assert(canAddLeg([], a).ok)
console.assert(canAddLeg([a], b).ok && canAddLeg([a], b).mode === 'sgm')
console.assert(!canAddLeg([a, b], c).ok)
console.assert(canAddLeg([a], c).ok && canAddLeg([a], c).mode === 'multi')
console.assert(slipMode([a, b]) === 'sgm')
console.assert(combinedOdds([a, b]) === 3.6)
// Different totals lines are both valid on an SGM (was wrongly treated as duplicate)
console.assert(canAddLeg([a, o15], o25).ok)
console.assert(!canAddLeg([o25], u25).ok, 'over vs under same line must conflict')
console.assert(!canAddLeg([o25], { ...o25, odds: 2.1 }).ok, 'exact same pick is duplicate')
console.log('slip_rules_ok')
