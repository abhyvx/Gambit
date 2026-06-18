const STYLES = {
  bet: 'verdict-bet',
  caution: 'verdict-caution',
  skip: 'verdict-skip',
  skip_match: 'verdict-skip',
}

const LABELS = {
  bet: 'BET',
  caution: 'CAUTION',
  skip: 'SKIP',
  skip_match: 'SKIP',
}

const ICONS = {
  bet: '✓',
  caution: '!',
  skip: '–',
  skip_match: '–',
}

export default function VerdictBadge({ verdict }) {
  const v = (verdict || 'skip').toLowerCase()
  return (
    <span className={`verdict-badge ${STYLES[v] || 'verdict-skip'}`}>
      <span className="verdict-dot" aria-hidden>{ICONS[v] || '–'}</span>
      {LABELS[v] || v.toUpperCase()}
    </span>
  )
}
