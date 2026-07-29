/** Orthodox angular G — classic open C + mid spur. Shared by logo + intro. */

/** Letterform C (gap on the right), readable as a G once the spur lands. */
export const G_RING = [
  [50, 18],
  [38, 10],
  [24, 10],
  [12, 20],
  [12, 44],
  [24, 54],
  [38, 54],
  [50, 46],
]

/** Spur from the opening into the bowl + short down-tick. */
export const G_SPUR = [
  [50, 32],
  [28, 32],
]

export const G_SPUR_CAP = [
  [50, 32],
  [50, 44],
]

export function gPolyline(points) {
  return points.map((p) => p.join(',')).join(' ')
}

export const G_EDGES = [
  ...G_RING.slice(0, -1).map((_, i) => ({ a: G_RING[i], b: G_RING[i + 1], kind: 'body' })),
  { a: G_SPUR[0], b: G_SPUR[1], kind: 'spur' },
  { a: G_SPUR_CAP[0], b: G_SPUR_CAP[1], kind: 'spur' },
]

export const G_NODES = (() => {
  const seen = new Map()
  for (const { a, b } of G_EDGES) {
    seen.set(a.join(','), a)
    seen.set(b.join(','), b)
  }
  return [...seen.values()]
})()

export function GambitMark({ size = 40, className = '' }) {
  return (
    <svg
      className={`gambit-mark ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden
    >
      <polyline
        className="gambit-mark-ring"
        points={gPolyline(G_RING)}
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="miter"
        strokeLinecap="square"
        fill="none"
      />
      <polyline
        className="gambit-mark-spur"
        points="28,32 50,32 50,44"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="miter"
        strokeLinecap="square"
        fill="none"
      />
      {G_NODES.map(([x, y], i) => (
        <rect
          key={i}
          className="gambit-mark-node"
          x={x - 0.85}
          y={y - 0.85}
          width="1.7"
          height="1.7"
          fill="currentColor"
        />
      ))}
      <title>Gambit</title>
    </svg>
  )
}

/** Full logo: mark G + “ambit” (the mark is the letter G). */
export default function GambitLogo({
  size = 40,
  showWord = true,
  className = '',
  stacked = false,
  word = 'AMBIT',
}) {
  return (
    <span className={`gambit-brand ${stacked ? 'is-stacked' : ''} ${className}`.trim()}>
      <GambitMark size={size} />
      {showWord && (
        <span
          className="gambit-word"
          style={{ fontSize: Math.max(17, Math.round(size * 0.7)) }}
        >
          {word}
        </span>
      )}
    </span>
  )
}
