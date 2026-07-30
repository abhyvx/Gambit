import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import LandingPage from './pages/LandingPage'
import HomePage from './pages/HomePage'
import SportPage from './pages/SportPage'
import WorldCupPage from './pages/WorldCupPage'
import GuidePage from './pages/GuidePage'
import ModelPage from './pages/ModelPage'
import PortfolioPage from './pages/PortfolioPage'
import SettingsPage from './pages/SettingsPage'
import AdminPage from './pages/AdminPage'
import AdminUsersPage from './pages/AdminUsersPage'
import { PrivacyPage, TermsPage } from './pages/LegalPages'
import { BankrollProvider } from './context/BankrollContext'
import { AuthProvider } from './context/AuthContext'
import './index.css'

export default function App() {
  return (
    <AuthProvider>
      <BankrollProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/app" element={<Layout />}>
              <Route index element={<HomePage />} />
              <Route path="sport/:sportId" element={<SportPage />} />
              <Route path="worldcup" element={<WorldCupPage />} />
              <Route path="model" element={<ModelPage />} />
              <Route path="portfolio" element={<PortfolioPage />} />
              <Route path="account" element={<SettingsPage />} />
              <Route path="settings" element={<Navigate to="/app/account" replace />} />
              <Route path="admin" element={<AdminPage />} />
              <Route path="admin/users" element={<AdminUsersPage />} />
              <Route path="legal/privacy" element={<PrivacyPage />} />
              <Route path="legal/terms" element={<TermsPage />} />
              <Route path="guide" element={<GuidePage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </BankrollProvider>
    </AuthProvider>
  )
}
