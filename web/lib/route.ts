'use client'
import { useEffect, useState } from 'react'

export type Route = 'login' | 'new' | 'queue' | 'admin'
const ROUTES: Route[] = ['login', 'new', 'queue', 'admin']

function read(): Route | null {
  const name = window.location.hash.replace(/^#\/?/, '').split(/[/?]/)[0] as Route
  return ROUTES.includes(name) ? name : null
}

/** Hash routing (#/queue) so the exported site works as plain static files and survives a reload. */
export function useRoute(): [Route | null, (r: Route) => void] {
  const [route, setRoute] = useState<Route | null>(null)
  useEffect(() => {
    const sync = () => setRoute(read())
    sync()
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  return [route, (r) => (window.location.hash = `#/${r}`)]
}
