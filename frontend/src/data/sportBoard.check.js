/** Spot-check: unique league logos + banner images; every top tab has a real logo. */
import { SPORT_GROUPS } from './sportBoard.js'

const logos = []
const images = []
for (const g of SPORT_GROUPS) {
  for (const lg of g.leagues) {
    if (lg.top === false) continue // All/Other tiles may share sport photo
    if (lg.logo) logos.push([lg.key, lg.logo])
    if (lg.image) images.push([lg.key, lg.image])
  }
}

const logoUrls = logos.map(([, u]) => u)
const imageUrls = images.map(([, u]) => u)
const dupLogo = logoUrls.filter((u, i) => logoUrls.indexOf(u) !== i)
const dupImg = imageUrls.filter((u, i) => imageUrls.indexOf(u) !== i)

if (dupLogo.length) {
  console.error('duplicate logos', [...new Set(dupLogo)])
  process.exit(1)
}
if (dupImg.length) {
  console.error('duplicate banner images', [...new Set(dupImg)])
  process.exit(1)
}

const missingLogo = []
const cricketKeys = []
for (const g of SPORT_GROUPS) {
  for (const lg of g.leagues) {
    if (lg.top && !lg.logo) missingLogo.push(lg.key)
    if (g.id === 'cricket') cricketKeys.push(lg.key)
  }
}
if (missingLogo.length) {
  console.error('missing logos', missingLogo)
  process.exit(1)
}

// Cricket stays lean — no empty franchise tabs
const allowedCricket = new Set(['cricket_all', 'cricket_international', 'cricket_domestic'])
const extra = cricketKeys.filter((k) => !allowedCricket.has(k))
if (extra.length || cricketKeys.length !== 3) {
  console.error('cricket tabs must be All/International/Domestic', cricketKeys)
  process.exit(1)
}

console.log('ok sportBoard unique', { logos: logos.length, images: images.length, cricket: cricketKeys })
