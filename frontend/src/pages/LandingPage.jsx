import { useNavigate } from 'react-router-dom'
import GambitLogo from '../components/GambitLogo'
import { markEntryFromLanding } from '../components/EntryScreen'
import './landing.css'

export default function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="landing">
      <header className="landing-top">
        <GambitLogo size={36} showWord />
        <span className="landing-tag-mini">18+</span>
      </header>

      <main className="landing-content">
        <h1 className="landing-title">GAMBIT</h1>
        <p className="landing-sub">
          Soccer, basketball, and cricket boards with prices.
        </p>
        <button
          type="button"
          className="landing-cta"
          onClick={() => {
            markEntryFromLanding()
            navigate('/app')
          }}
        >
          Enter
        </button>
      </main>
    </div>
  )
}
