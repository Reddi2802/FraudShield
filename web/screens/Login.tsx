'use client'
import { useState } from 'react'
import { ChevronRight, ShieldCheck } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import type { Customer, Role } from '@/lib/types'

export function Login() {
  const { login } = useAuth()
  const [role, setRole] = useState<Role>('customer')
  const [email, setEmail] = useState('seed.customer.00001@example.invalid')
  const [password, setPassword] = useState('ChangeMe123!')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password, role)
      window.location.hash = role === 'customer' ? '#/new' : '#/queue'
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to log in')
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="login-page">
      <div className="login-art">
        <div className="brand">
          <span className="brand-mark">
            <ShieldCheck />
          </span>
          <span>
            Fraud<span>Shield</span>
          </span>
        </div>
        <div className="art-copy">
          <p className="eyebrow">Transaction intelligence</p>
          <h1>
            Make every decision
            <br />
            <em>defensible.</em>
          </h1>
          <p>One console for signals, decisions, and the human judgment behind them.</p>
        </div>
      </div>
      <div className="login-panel">
        <div className="login-form">
          <p className="eyebrow">Welcome back</p>
          <h2>Sign in to your workspace</h2>
          <p className="muted-text">Use a demo account to explore the console.</p>
          <form onSubmit={submit}>
            <label>
              Email
              <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
            </label>
            <label>
              Password
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                type="password"
                required
              />
            </label>
            <label>
              Workspace role
              <select
                value={role}
                onChange={(e) => {
                  const r = e.target.value as Role
                  setRole(r)
                  setEmail(
                    r === 'customer'
                      ? 'seed.customer.00001@example.invalid'
                      : 'investigator1@example.invalid',
                  )
                }}
              >
                <option value="customer">Customer</option>
                <option value="investigator">Investigator</option>
              </select>
            </label>
            {error && <div className="error-box">{error}</div>}
            <button className="primary-button" disabled={busy}>
              {busy ? 'Signing in…' : 'Continue to workspace'}
              <ChevronRight />
            </button>
          </form>
          <div className="hint">
            <strong>Demo access</strong>
            <span>Password: ChangeMe123!</span>
            <span>Customer: seed.customer.00001@example.invalid</span>
            <span>Investigator: investigator1@example.invalid</span>
          </div>
          <p className="muted-text">
            <a href="#/admin">View the admin overview (read-only demo, no login)</a>
          </p>
        </div>
      </div>
    </main>
  )
}
