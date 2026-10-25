'use client'
import { useEffect, useState } from 'react'
import { LogOut, Moon, ShieldCheck, Sun } from 'lucide-react'
import { useAuth } from '@/lib/auth'

export function Header({ title, action }: { title: string; action?: React.ReactNode }) {
  const { email, role, logout } = useAuth()
  const [dark, setDark] = useState(false)
  useEffect(() => {
    setDark(localStorage.getItem('fraudshield_theme') === 'dark')
  }, [])
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])
  const toggleTheme = () => {
    const next = !dark
    setDark(next)
    localStorage.setItem('fraudshield_theme', next ? 'dark' : 'light')
  }
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">
          <ShieldCheck />
        </span>
        <span>
          Fraud<span>Shield</span>
        </span>
      </div>
      <div className="topbar-main">
        <div>
          <p className="eyebrow">{role === 'customer' ? 'Customer portal' : 'Operations console'}</p>
          <h1>{title}</h1>
        </div>
        {action}
      </div>
      <div className="user-menu">
        <button className="icon-button" onClick={toggleTheme} aria-label="Toggle dark mode">
          {dark ? <Sun /> : <Moon />}
        </button>
        <div className="user-info">
          <strong>{email || 'Demo workspace'}</strong>
          <span>{role ? `${role} account` : 'read-only demo'}</span>
        </div>
        {role && (
          <button className="logout" onClick={logout}>
            <LogOut /> <span>Log out</span>
          </button>
        )}
      </div>
    </header>
  )
}
