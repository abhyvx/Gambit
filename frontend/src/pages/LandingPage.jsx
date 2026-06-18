import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import './landing.css'

const BRAND = 'GAMBIT'

// Brand stops (violet -> magenta -> cyan) for depth-tinted dots.
function mix(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}
const C1 = [124, 92, 255]
const C2 = [176, 108, 255]
const C3 = [33, 212, 253]

export default function LandingPage() {
  const canvasRef = useRef(null)
  const navigate = useNavigate()
  const [entering, setEntering] = useState(false)
  const anim = useRef({ rot: 0, speed: 0.0016, scale: 1, target: 1, raf: 0 })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    // Fibonacci sphere — evenly distributed points.
    const N = 900
    const pts = []
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2
      const r = Math.sqrt(Math.max(0, 1 - y * y))
      const theta = i * 2.399963229728653
      pts.push([Math.cos(theta) * r, y, Math.sin(theta) * r, Math.random() < 0.06])
    }

    let w = 0
    let h = 0
    let dpr = Math.min(window.devicePixelRatio || 1, 2)
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = window.innerWidth
      h = window.innerHeight
      canvas.width = w * dpr
      canvas.height = h * dpr
      canvas.style.width = w + 'px'
      canvas.style.height = h + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const tilt = -0.42
    const ct = Math.cos(tilt)
    const st = Math.sin(tilt)

    const draw = () => {
      const a = anim.current
      a.rot += a.speed
      a.scale += (a.target - a.scale) * 0.06
      if (a.speed > 0.0016) a.speed += (0.0016 - a.speed) * 0.02

      ctx.clearRect(0, 0, w, h)
      // globe sits low so the top half reads as a horizon
      const cx = w * 0.5
      const cy = h * (w < 760 ? 0.6 : 0.74)
      const R = Math.min(w * 0.42, h * 0.62) * a.scale

      const cosR = Math.cos(a.rot)
      const sinR = Math.sin(a.rot)

      // soft core glow
      const glow = ctx.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.05)
      glow.addColorStop(0, 'rgba(124,92,255,0.22)')
      glow.addColorStop(0.6, 'rgba(33,212,253,0.06)')
      glow.addColorStop(1, 'rgba(5,4,20,0)')
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(cx, cy, R * 1.05, 0, Math.PI * 2)
      ctx.fill()

      for (let i = 0; i < pts.length; i++) {
        const p = pts[i]
        // rotate around Y
        let x = p[0] * cosR - p[2] * sinR
        let z = p[0] * sinR + p[2] * cosR
        let y = p[1]
        // tilt around X
        const y2 = y * ct - z * st
        const z2 = y * st + z * ct
        const depth = (z2 + 1) / 2 // 0 back .. 1 front
        const sx = cx + x * R
        const sy = cy - y2 * R
        const lat = (p[1] + 1) / 2
        const col = lat < 0.5 ? mix(C1, C2, lat * 2) : mix(C2, C3, (lat - 0.5) * 2)
        const isHot = p[3]
        const size = (isHot ? 2.4 : 1.5) * (0.45 + depth * 0.95) * a.scale
        const alpha = (isHot ? 0.95 : 0.5) * (0.18 + depth * 0.82)
        ctx.beginPath()
        ctx.fillStyle = `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${alpha})`
        ctx.arc(sx, sy, size, 0, Math.PI * 2)
        ctx.fill()
        if (isHot && depth > 0.6) {
          ctx.beginPath()
          ctx.fillStyle = `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${0.12 * depth})`
          ctx.arc(sx, sy, size * 3.2, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      a.raf = requestAnimationFrame(draw)
    }
    draw()

    return () => {
      cancelAnimationFrame(anim.current.raf)
      window.removeEventListener('resize', resize)
    }
  }, [])

  const enter = () => {
    if (entering) return
    setEntering(true)
    anim.current.speed = 0.05
    anim.current.target = 2.6
    setTimeout(() => navigate('/app'), 1050)
  }

  return (
    <div className={`landing ${entering ? 'is-entering' : ''}`} onClick={enter}>
      <canvas ref={canvasRef} className="landing-globe" />
      <div className="landing-grain" aria-hidden />

      <header className="landing-top">
        <span className="landing-mark">
          <span className="landing-dot" /> {BRAND}
        </span>
        <span className="landing-tag-mini">18+ · bet responsibly</span>
      </header>

      <div className="landing-content">
        <p className="landing-eyebrow">World Cup 2026 · live Stake prices</p>
        <h1 className="landing-title">
          The whole board.<br />
          <span className="grad">One honest read.</span>
        </h1>
        <p className="landing-sub">
          Every market Stake offers — graded by our model, with the smartest singles
          first and a straight-talking warning before any parlay.
        </p>
        <button className="landing-cta" onClick={enter}>
          Enter the floor
          <span className="landing-cta-arrow">→</span>
        </button>
        <p className="landing-hint">click anywhere to spin in</p>
      </div>
    </div>
  )
}
