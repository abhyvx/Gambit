/** ponytail: slip rule self-check — fails if multi/SGM gates regress. */
import { canAddLeg, slipMode, combinedOdds } from '../lib/slipRules.js'

const a = { eventId: '1', market: 'mw', selection: 'home', odds: 2 }
const b = { eventId: '1', market: 'btts', selection: 'yes', odds: 1.8 }
const c = { eventId: '2', market: 'mw', selection: 'home', odds: 1.5 }

console.assert(canAddLeg([], a).ok)
console.assert(canAddLeg([a], b).ok && canAddLeg([a], b).mode === 'sgm')
console.assert(!canAddLeg([a, b], c).ok)
console.assert(canAddLeg([a], c).ok && canAddLeg([a], c).mode === 'multi')
console.assert(slipMode([a, b]) === 'sgm')
console.assert(combinedOdds([a, b]) === 3.6)
console.log('slip_rules_ok')
