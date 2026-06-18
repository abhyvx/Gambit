import { useEffect, useRef, useState } from 'react'

const prefersReduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * Smoothly counts up to `value`. `format` maps the live numeric value to a string.
 * Falls back to the final value instantly when reduced motion is requested.
 */
export default function AnimatedNumber({ value = 0, format = (n) => String(Math.round(n)), duration = 650, className }) {
  const [display, setDisplay] = useState(value)
  const fromRef = useRef(value)
  const rafRef = useRef(null)

  useEffect(() => {
    const target = Number(value) || 0
    if (prefersReduced()) {
      setDisplay(target)
      return
    }
    const from = Number(fromRef.current) || 0
    if (from === target) {
      setDisplay(target)
      return
    }
    const start = performance.now()
    const tick = (now) => {
      const p = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      setDisplay(from + (target - from) * eased)
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = target
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [value, duration])

  return <span className={className}>{format(display)}</span>
}
