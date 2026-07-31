import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'
import App from './App.tsx'
import { LoginGate } from './LoginGate.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LoginGate>
      {(user, onLogout) => <App user={user} onLogout={onLogout} />}
    </LoginGate>
  </StrictMode>,
)
