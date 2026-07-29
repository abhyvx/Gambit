import { Navigate } from 'react-router-dom'

/** World Cup lives under Soccer leagues on the sport page. */
export default function WorldCupPage() {
  return <Navigate to="/app/sport/soccer?league=soccer_fifa_world_cup" replace />
}
