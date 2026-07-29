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
  bet: '+',
  caution: '!',
  skip: 'x',
  skip_match: 'x',
}

export default function VerdictBadge({ verdict }) {
  const v = (verdict || 'skip').toLowerCase()
  return (
    <span className={`verdict-badge ${STYLES[v] || 'verdict-skip'}`}>
      <span className="verdict-dot" aria-hidden>{ICONS[v] || 'x'}</span>
      {LABELS[v] || v.toUpperCase()}
    </span>
  )
}
