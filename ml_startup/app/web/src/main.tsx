import { createRoot } from 'react-dom/client'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-mono/400.css'
import './styles.css'
import App from './App'

// A tab opened before a new deploy asks for script files that no longer exist.
// Reload once to pick up the new version instead of showing a blank page.
addEventListener('vite:preloadError', (e) => {
  e.preventDefault()
  try {
    // At most one reload every 30 s, so a real outage can't cause a reload loop
    const last = Number(sessionStorage.getItem('reloaded-for-deploy') ?? 0)
    if (Date.now() - last < 30000) return
    sessionStorage.setItem('reloaded-for-deploy', String(Date.now()))
  } catch { /* storage blocked: reload anyway */ }
  location.reload()
})

createRoot(document.getElementById('root')!).render(<App />)
