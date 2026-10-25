'use client'
import { BarChart3, ClipboardList, LayoutDashboard, LogIn, Plus, ShieldCheck, type LucideIcon } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import type { Route } from '@/lib/route'

type Item = { key: Route; label: string; Icon: LucideIcon }

export function Sidebar({ page, setPage }: { page: Route; setPage: (p: Route) => void }) {
  const { role } = useAuth()
  const items: Item[] =
    role === 'investigator'
      ? [
          { key: 'queue', label: 'Case queue', Icon: ClipboardList },
          { key: 'admin', label: 'Admin overview', Icon: LayoutDashboard },
        ]
      : role === 'customer'
        ? [
            { key: 'new', label: 'New transaction', Icon: Plus },
            { key: 'admin', label: 'Admin view (demo)', Icon: BarChart3 },
          ]
        : [
            { key: 'login', label: 'Sign in', Icon: LogIn },
            { key: 'admin', label: 'Admin view (demo)', Icon: BarChart3 },
          ]
  return (
    <aside className="sidebar">
      <div className="mobile-brand">FraudShield</div>
      <nav>
        {items.map(({ key, label, Icon }) => (
          <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>
            <Icon />
            {label}
          </button>
        ))}
      </nav>
      <div className="sidebar-note">
        <ShieldCheck />
        <p>
          <strong>Every decision is explained</strong>
          <br />
          Each score shows which agents contributed.
        </p>
      </div>
    </aside>
  )
}
