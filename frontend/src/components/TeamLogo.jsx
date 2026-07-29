/** Team crest / national flag - ESPN first, then flagcdn, then sports DB, then shield. */
import { useEffect, useState } from 'react'
import { flagUrl, countryIso } from '../data/flags'

function slugName(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

/** Extra crest guesses when ESPN URL is missing (India / Stake-blocked boards). */
function crestFallbacks(name, sport = '') {
  const slug = slugName(name)
  if (!slug) return []
  const out = []
  // Common ESPN CDN slug paths (works for many clubs without an id)
  const espnSport = sport.startsWith('basket') ? 'nba'
    : sport.startsWith('cricket') ? 'cricket'
      : 'soccer'
  out.push(`https://a.espncdn.com/combiner/i?img=/i/teamlogos/${espnSport}/500/${slug}.png&w=100&h=100`)
  // TheSportsDB free search thumb (works without Stake) - slug guess only
  out.push(`https://www.thesportsdb.com/images/media/team/badge/${slug}.png`)
  out.push(`https://r2.thesportsdb.com/images/media/team/badge/${slug}.png`)
  return out
}

export default function TeamLogo({ name, src, size = 36, preferFlag = false, sport = '' }) {
  const flag = flagUrl(name, size >= 40 ? 80 : 40)
  const isNational = Boolean(countryIso(name))
  const useFlagFirst = preferFlag || (isNational && !src)
  const extras = !isNational ? crestFallbacks(name, sport) : []
  // Always allow flag as late fallback for internationals even when src was provided but failed
  const candidates = useFlagFirst
    ? [flag, src, ...extras].filter(Boolean)
    : [src, ...extras, flag].filter(Boolean)
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    setIdx(0)
  }, [name, src, sport])

  const current = candidates[idx]

  if (current && idx < candidates.length) {
    return (
      <img
        key={`${name}-${current}`}
        className={`team-logo ${current === flag ? 'is-flag' : ''}`}
        src={current}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setIdx((i) => i + 1)}
      />
    )
  }

  // Last resort: monogram disc (single letter), never empty void
  const letter = (name || '?').trim().charAt(0).toUpperCase() || '?'
  return (
    <span
      className="team-crest team-crest--mono"
      style={{ width: size, height: size, fontSize: Math.max(11, size * 0.42) }}
      title={name || ''}
      aria-hidden
    >
      {letter}
    </span>
  )
}
