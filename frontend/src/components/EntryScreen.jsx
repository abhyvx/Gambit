import { useEffect, useRef, useState } from 'react'
import { G_EDGES, G_NODES } from './GambitLogo'
import './EntryScreen.css'

const FAST_MIN_MS = 2200
const PLAY_MS = 2600
const HOLD_PULSE_MS = 800
const RESOLVE_MS = 250
const FADE_MS = 220
const MAX_MS = 4000
const REDUCED_MS = 280
const PLAY_FLAG = 'gambit_play_entry'

let _ready = false
const _waiters = new Set()
const _replayListeners = new Set()

export function signalEntryReady() {
  if (_ready) return
  _ready = true
  _waiters.forEach((fn) => fn())
  _waiters.clear()
}

function whenReady() {
  if (_ready) return Promise.resolve()
  return new Promise((resolve) => { _waiters.add(resolve) })
}

export function useEntryReady(isReady = true) {
  useEffect(() => {
    if (isReady) signalEntryReady()
  }, [isReady])
}

export function markEntryFromLanding() {
  try { sessionStorage.setItem(PLAY_FLAG, '1') } catch { /* ignore */ }
}

export function requestEntryReplay(_reason = 'nav') {}

function isHardRefresh() {
  try {
    const nav = performance.getEntriesByType?.('navigation')?.[0]
    return nav?.type === 'reload'
  } catch {
    return false
  }
}

function consumePlayFlag() {
  try {
    if (sessionStorage.getItem(PLAY_FLAG) === '1') {
      sessionStorage.removeItem(PLAY_FLAG)
      return true
    }
  } catch { /* ignore */ }
  return false
}

function shouldPlayEntry() {
  if (isHardRefresh()) return true
  return consumePlayFlag()
}

function prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function dist2(a, b) {
  const dx = a[0] - b[0]
  const dy = a[1] - b[1]
  return dx * dx + dy * dy
}

function nearestSeat(pt, seats) {
  let best = seats[0]
  let bestD = Infinity
  for (const s of seats) {
    const d = dist2(pt, s)
    if (d < bestD) {
      bestD = d
      best = s
    }
  }
  return best
}

function KgMark({ runId, reduced }) {
  // King's Gambit geometry on the G (equal file/rank): e4-e5 vertical, e4-f4 horizontal
  // Spur bar [28,32]→[50,32]; body top y=10. Δ = 22 both ways.
  const e4 = [28, 32] // left end of spur
  const f4 = [50, 32] // right end of spur
  const e5 = [28, 10] // above e4 on the body
  const seats = [e4, e5, f4]

  const moves = [
    { ch: '♙', from: [28, 54], to: e4, cls: 'is-e4', begin: '0s', size: 6.0 },
    { ch: '♟', from: [28, -2], to: e5, cls: 'is-e5', begin: '0.14s', size: 5.0 },
    { ch: '♙', from: [50, 54], to: f4, cls: 'is-f4', begin: '0.28s', size: 6.6 },
  ]

  const spokes = []
  G_EDGES.forEach(({ a, b, kind }, i) => {
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    const origin = nearestSeat(mid, seats)
    spokes.push({ a: origin, b: a, kind, d: 0.7 + (i % 5) * 0.03 })
    spokes.push({ a: origin, b: b, kind, d: 0.74 + (i % 5) * 0.03 })
  })

  const bg = [
    { a: e4, b: [14, 20], d: 0.85 },
    { a: e4, b: [18, 46], d: 1.15 },
    { a: e4, b: [40, 18], d: 1.0 },
    { a: e5, b: [12, 34], d: 0.95 },
    { a: e5, b: [46, 24], d: 1.25 },
    { a: e5, b: [22, 48], d: 1.35 },
    { a: f4, b: [42, 14], d: 1.05 },
    { a: f4, b: [36, 50], d: 1.4 },
    { a: f4, b: [20, 28], d: 1.2 },
    { a: [16, 26], b: [44, 44], d: 1.3 },
  ]

  return (
    <svg key={runId} className="entry-mark" viewBox="0 0 64 64" aria-hidden>
      {!reduced && bg.map((e, i) => (
        <line
          key={`bg${i}`}
          className="entry-line entry-line--web"
          x1={e.a[0]}
          y1={e.a[1]}
          x2={e.b[0]}
          y2={e.b[1]}
          pathLength="100"
          style={{ animationDelay: `${e.d}s` }}
        />
      ))}

      {!reduced && spokes.map((e, i) => (
        <line
          key={`sp${i}`}
          className={e.kind === 'spur' ? 'entry-line entry-line--spoke entry-line--spoke-spur' : 'entry-line entry-line--spoke'}
          x1={e.a[0]}
          y1={e.a[1]}
          x2={e.b[0]}
          y2={e.b[1]}
          pathLength="100"
          style={{ animationDelay: `${e.d}s` }}
        />
      ))}

      {G_EDGES.map(({ a, b, kind }, i) => (
        <line
          key={`g${i}`}
          className={kind === 'spur' ? 'entry-line entry-line--g entry-line--spur' : 'entry-line entry-line--g'}
          x1={a[0]}
          y1={a[1]}
          x2={b[0]}
          y2={b[1]}
          pathLength="100"
          style={{ animationDelay: `${0.85 + i * 0.05}s` }}
        />
      ))}

      {G_NODES.map(([x, y], i) => (
        <rect
          key={`n${i}`}
          className="entry-dot"
          x={x - 0.5}
          y={y - 0.5}
          width="1"
          height="1"
          style={{ animationDelay: `${0.95 + i * 0.03}s` }}
        />
      ))}

      {!reduced && moves.map((m) => (
        <g key={m.cls} className={`entry-pawn-g ${m.cls}`} transform={`translate(${m.from[0]} ${m.from[1]})`}>
          <animateTransform
            attributeName="transform"
            type="translate"
            from={`${m.from[0]} ${m.from[1]}`}
            to={`${m.to[0]} ${m.to[1]}`}
            dur="0.55s"
            begin={m.begin}
            fill="freeze"
            calcMode="spline"
            keySplines="0.22 0.9 0.2 1"
            keyTimes="0;1"
          />
          <text
            className={`entry-pawn ${m.cls}`}
            textAnchor="middle"
            dominantBaseline="central"
            x="0"
            y="0"
            style={{ fontSize: `${m.size}px` }}
          >
            {m.ch}
          </text>
        </g>
      ))}
    </svg>
  )
}

export default function EntryScreen({ children }) {
  const [phase, setPhase] = useState(() => (shouldPlayEntry() ? 'play' : 'done'))
  const [runId, setRunId] = useState(0)
  const [reduced] = useState(prefersReducedMotion)
  const finishing = useRef(false)
  const skipRef = useRef(false)
  const playThisMount = useRef(phase !== 'done')

  const finish = () => {
    if (finishing.current || phase === 'done') return
    finishing.current = true
    skipRef.current = true
    signalEntryReady()
    setPhase('out')
    setTimeout(() => setPhase('done'), FADE_MS)
  }

  useEffect(() => {
    const onReplay = () => {
      if (!consumePlayFlag() && !isHardRefresh()) return
      finishing.current = false
      skipRef.current = false
      playThisMount.current = true
      _ready = false
      setPhase('play')
      setRunId((n) => n + 1)
    }
    _replayListeners.add(onReplay)
    return () => { _replayListeners.delete(onReplay) }
  }, [])

  useEffect(() => {
    if (!playThisMount.current && phase === 'done') {
      signalEntryReady()
      return undefined
    }
    let cancelled = false
    finishing.current = false
    skipRef.current = false

    ;(async () => {
      if (reduced) {
        await Promise.race([whenReady(), sleep(MAX_MS)])
        if (cancelled || skipRef.current) return
        await sleep(REDUCED_MS)
        if (cancelled || skipRef.current) return
        finishing.current = true
        setPhase('out')
        setTimeout(() => { if (!cancelled) setPhase('done') }, FADE_MS)
        return
      }

      setPhase('play')
      const ceiling = sleep(MAX_MS)
      const ready = whenReady()

      await Promise.race([
        Promise.all([ready, sleep(FAST_MIN_MS)]),
        sleep(PLAY_MS),
      ])
      if (cancelled || skipRef.current) return

      if (!_ready) {
        setPhase('hold')
        await Promise.race([ready, ceiling])
        if (cancelled || skipRef.current) return
        await sleep(80)
      }

      if (cancelled || skipRef.current) return
      setPhase('resolve')
      await sleep(RESOLVE_MS)
      if (cancelled || skipRef.current) return

      finishing.current = true
      setPhase('out')
      setTimeout(() => { if (!cancelled) setPhase('done') }, FADE_MS)
    })()

    return () => { cancelled = true }
  }, [reduced, runId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (phase === 'done') return undefined
    const onKey = (e) => {
      if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        finish()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase]) // eslint-disable-line react-hooks/exhaustive-deps

  const showOverlay = phase !== 'done'

  return (
    <>
      <div className={showOverlay ? 'entry-app-under' : undefined} aria-hidden={showOverlay || undefined}>
        {children}
      </div>

      {showOverlay && (
        <div
          className={[
            'entry-screen',
            phase === 'out' ? 'is-out' : '',
            phase === 'hold' ? 'is-hold' : '',
            phase === 'resolve' ? 'is-resolve' : '',
            reduced ? 'is-reduced' : '',
          ].filter(Boolean).join(' ')}
          aria-busy="true"
          aria-label="Gambit"
          onClick={finish}
          role="presentation"
          style={phase === 'hold' ? { '--hold-ms': `${HOLD_PULSE_MS}ms` } : undefined}
        >
          <div className="entry-reveal entry-reveal--brand" aria-label="Gambit">
            <KgMark runId={runId} reduced={reduced} />
            <span className={`entry-ambit gambit-word${reduced ? ' is-static' : ''}`}>AMBIT</span>
          </div>
          {phase === 'hold' && !reduced && (
            <p className="entry-hold-hint" aria-live="polite">Loading…</p>
          )}
          <button type="button" className="entry-skip" onClick={(e) => { e.stopPropagation(); finish() }}>
            Skip
          </button>
        </div>
      )}
    </>
  )
}
