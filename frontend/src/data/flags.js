/** National-team name → ISO 3166-1 alpha-2 for flagcdn. */
const COUNTRY_ISO = {
  argentina: 'ar', australia: 'au', austria: 'at', belgium: 'be', brazil: 'br',
  cameroon: 'cm', canada: 'ca', chile: 'cl', china: 'cn', colombia: 'co',
  croatia: 'hr', denmark: 'dk', ecuador: 'ec', egypt: 'eg', england: 'gb-eng',
  finland: 'fi', france: 'fr', germany: 'de', ghana: 'gh', greece: 'gr',
  india: 'in', indonesia: 'id', iran: 'ir', iraq: 'iq', ireland: 'ie',
  italy: 'it', jamaica: 'jm', japan: 'jp', kenya: 'ke', mexico: 'mx',
  morocco: 'ma', netherlands: 'nl', 'new zealand': 'nz', nigeria: 'ng',
  norway: 'no', pakistan: 'pk', paraguay: 'py', peru: 'pe', poland: 'pl',
  portugal: 'pt', qatar: 'qa', romania: 'ro', russia: 'ru', 'saudi arabia': 'sa',
  scotland: 'gb-sct', senegal: 'sn', serbia: 'rs', 'south africa': 'za',
  'south korea': 'kr', korea: 'kr', spain: 'es', sweden: 'se', switzerland: 'ch',
  thailand: 'th', tunisia: 'tn', turkey: 'tr', 'türkiye': 'tr', ukraine: 'ua',
  'united states': 'us', usa: 'us', uruguay: 'uy', venezuela: 've', wales: 'gb-wls',
  zimbabwe: 'zw', bangladesh: 'bd', 'sri lanka': 'lk', afghanistan: 'af',
  nepal: 'np', 'hong kong': 'hk', 'west indies': 'tt', // WI → Trinidad as stand-in
  'northern ireland': 'gb-nir', uae: 'ae', 'united arab emirates': 'ae',
  oman: 'om', namibia: 'na', netherlands: 'nl', scotland: 'gb-sct',
  iceland: 'is', hungary: 'hu', bulgaria: 'bg', czechia: 'cz', 'czech republic': 'cz',
  slovakia: 'sk', slovenia: 'si', albania: 'al', bosnia: 'ba', 'bosnia and herzegovina': 'ba',
  georgia: 'ge', armenia: 'am', azerbaijan: 'az', kazakhstan: 'kz', uzbekistan: 'uz',
  bahrain: 'bh', kuwait: 'kw', malaysia: 'my', singapore: 'sg', philippines: 'ph',
  vietnam: 'vn', taiwan: 'tw', 'chinese taipei': 'tw', mongolia: 'mn',
  uganda: 'ug', tanzania: 'tz', rwanda: 'rw', ethiopia: 'et', algeria: 'dz',
  'ivory coast': "ci", "côte d'ivoire": 'ci', 'cote divoire': 'ci',
  gibraltar: 'gi', malta: 'mt', cyprus: 'cy', luxembourg: 'lu',
  fiji: 'fj', samoa: 'ws', png: 'pg', 'papua new guinea': 'pg',
}

export function countryIso(name) {
  if (!name) return null
  const n = String(name).toLowerCase().trim()
  if (COUNTRY_ISO[n]) return COUNTRY_ISO[n]
  // "India Women" / "India Under-19s"
  for (const [k, iso] of Object.entries(COUNTRY_ISO)) {
    if (n === k || n.startsWith(`${k} `) || n.startsWith(`${k}-`)) return iso
  }
  return null
}

export function flagUrl(name, w = 80) {
  const iso = countryIso(name)
  if (!iso) return null
  return `https://flagcdn.com/w${w}/${iso}.png`
}
