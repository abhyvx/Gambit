import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import LandingPage from './pages/LandingPage'
import WorldCupPage from './pages/WorldCupPage'
import GuidePage from './pages/GuidePage'
import SettingsPage from './pages/SettingsPage'
import ModelPage from './pages/ModelPage'
import PortfolioPage from './pages/PortfolioPage'
import { BankrollProvider } from './context/BankrollContext'
import './index.css'

export default function App() {
  return (
    <BankrollProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/app" element={<Layout />}>
            <Route index element={<WorldCupPage />} />
            <Route path="model" element={<ModelPage />} />
            <Route path="portfolio" element={<PortfolioPage />} />
            <Route path="guide" element={<GuidePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </BankrollProvider>
  )
}
