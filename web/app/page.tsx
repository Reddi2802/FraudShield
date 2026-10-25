'use client'
import { Sidebar } from '@/components/Sidebar'
import { AuthProvider, useAuth } from '@/lib/auth'
import { useRoute, type Route } from '@/lib/route'
import { AdminPage } from '@/screens/AdminPage'
import { CustomerPage } from '@/screens/CustomerPage'
import { InvestigatorPage } from '@/screens/InvestigatorPage'
import { Login } from '@/screens/Login'

function App() {
  const auth = useAuth()
  const [route, go] = useRoute()
  if (!auth.ready) return null

  // The Admin overview is a read-only demo page with no login (ADR-010), so it is reachable signed out.
  if (route === 'admin') {
    return (
      <div className="app-shell">
        <Sidebar page="admin" setPage={go} />
        <main className="main-area">
          <AdminPage />
        </main>
      </div>
    )
  }
  if (!auth.token || !auth.role) return <Login />

  const home: Route = auth.role === 'investigator' ? 'queue' : 'new'
  // A role may only open its own page; anything else falls back to home.
  const page: Route = route === home ? route : home
  return (
    <div className="app-shell">
      <Sidebar page={page} setPage={go} />
      <main className="main-area">{page === 'queue' ? <InvestigatorPage /> : <CustomerPage />}</main>
    </div>
  )
}

export default function Page() {
  return (
    <AuthProvider>
      <App />
    </AuthProvider>
  )
}
