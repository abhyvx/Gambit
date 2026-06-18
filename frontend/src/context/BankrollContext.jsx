import { createContext, useContext, useState } from 'react'

const MATCH_PRESETS = [100, 200, 300, 500, 750]

const BankrollContext = createContext()

export function BankrollProvider({ children }) {
  const [perMatchBudget, setPerMatchBudget] = useState(() => {
    const saved = localStorage.getItem('per_match_budget_inr')
    return saved ? Number(saved) : 300
  })

  const updatePerMatchBudget = (val) => {
    const n = Math.max(50, Math.min(5000, Number(val) || 300))
    setPerMatchBudget(n)
    localStorage.setItem('per_match_budget_inr', String(n))
  }

  return (
    <BankrollContext.Provider value={{
      perMatchBudget,
      updatePerMatchBudget,
      presets: MATCH_PRESETS,
      currency: 'INR',
      // legacy alias for pages still using bankroll
      bankroll: perMatchBudget,
      updateBankroll: updatePerMatchBudget,
    }}>
      {children}
    </BankrollContext.Provider>
  )
}

export function useBankroll() {
  return useContext(BankrollContext)
}

export function formatINR(n) {
  return `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}
