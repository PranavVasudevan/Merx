import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './theme.css'
import './skin-terminal.css'
import './tailwind.css'
import { initSkin } from './skin.ts'
import App from './App.tsx'
import { LoginGate } from './LoginGate.tsx'

initSkin()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LoginGate>
      {(user, onLogout) => (
        <BrowserRouter>
          <App user={user} onLogout={onLogout} />
        </BrowserRouter>
      )}
    </LoginGate>
  </StrictMode>,
)
