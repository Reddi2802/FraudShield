'use client'
import { createContext, useContext, useEffect, useState } from 'react'
import type { Role } from './types'
import { api, setToken, TOKEN_KEY } from './api'

type Auth = {
  ready: boolean // false until sessionStorage has been read, so a reload never flashes the login screen
  token: string
  role: Role | null
  email: string
  userId: number | null
  login: (email: string, password: string, role: Role) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false)
  const [token, setT] = useState('')
  const [role, setRole] = useState<Role | null>(null)
  const [email, setEmail] = useState('')
  const [userId, setUserId] = useState<number | null>(null)

  useEffect(() => {
    const t = sessionStorage.getItem(TOKEN_KEY)
    if (t) {
      setT(t)
      setToken(t)
      setRole(sessionStorage.getItem('fraudshield_role') as Role | null)
      setEmail(sessionStorage.getItem('fraudshield_email') || '')
      const id = sessionStorage.getItem('fraudshield_user_id')
      setUserId(id ? Number(id) : null)
    }
    setReady(true)
    // A 401 anywhere clears sessionStorage and moves the hash to #/login; mirror that in state.
    const onHash = () => {
      if (!sessionStorage.getItem(TOKEN_KEY)) {
        setT('')
        setToken('')
        setRole(null)
        setEmail('')
        setUserId(null)
      }
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  async function login(e: string, p: string, r: Role) {
    const result = await api.login(e, p, r)
    setToken(result.access_token)
    setT(result.access_token)
    setRole(result.role)
    setEmail(e)
    setUserId(result.user_id)
    sessionStorage.setItem(TOKEN_KEY, result.access_token)
    sessionStorage.setItem('fraudshield_role', result.role)
    sessionStorage.setItem('fraudshield_email', e)
    sessionStorage.setItem('fraudshield_user_id', String(result.user_id))
  }

  function logout() {
    sessionStorage.clear()
    setToken('')
    setT('')
    setRole(null)
    setEmail('')
    setUserId(null)
    window.location.hash = '#/login'
  }

  return <AuthContext.Provider value={{ ready, token, role, email, userId, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be inside AuthProvider')
  return context
}
