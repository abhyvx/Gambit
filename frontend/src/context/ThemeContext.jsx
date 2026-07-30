import { createContext, useContext, useEffect, useMemo, useState } from 'react'

const KEY = 'gambit_theme'
const ThemeContext = createContext({
  theme: 'dark',
  isLight: false,
  setTheme: () => {},
  toggleTheme: () => {},
})

function readStored() {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'light' || v === 'dark') return v
  } catch { /* private mode */ }
  return 'dark'
}

function applyDom(theme) {
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  root.style.colorScheme = theme
}

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    const initial = typeof document !== 'undefined' ? readStored() : 'dark'
    if (typeof document !== 'undefined') applyDom(initial)
    return initial
  })

  useEffect(() => {
    applyDom(theme)
    try { localStorage.setItem(KEY, theme) } catch { /* ignore */ }
  }, [theme])

  const value = useMemo(() => ({
    theme,
    isLight: theme === 'light',
    setTheme: (next) => {
      const t = next === 'light' ? 'light' : 'dark'
      setThemeState(t)
    },
    toggleTheme: () => setThemeState((t) => (t === 'light' ? 'dark' : 'light')),
  }), [theme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
