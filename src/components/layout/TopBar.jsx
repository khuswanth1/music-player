import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { ChevronLeft, ChevronRight, Crown, LogOut, Search, Settings, Shield, Wifi, WifiOff } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useRealtime } from '../../context/RealtimeContext'
import { Avatar } from '../ui'

export default function TopBar({ scrolled }) {
  const { user, logout, can } = useAuth()
  const { status } = useRealtime()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const [menu, setMenu] = useState(false)
  const menuRef = useRef(null)
  const onSearch = location.pathname.startsWith('/search')
  const [q, setQ] = useState(params.get('q') || '')

  useEffect(() => {
    if (onSearch) setQ(params.get('q') || '')
  }, [onSearch, params])

  useEffect(() => {
    if (!menu) return undefined
    const close = (e) => !menuRef.current?.contains(e.target) && setMenu(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menu])

  const updateQuery = (value) => {
    setQ(value)
    navigate(value ? `/search?q=${encodeURIComponent(value)}` : '/search', { replace: onSearch })
  }

  return (
    <header className={`sticky top-0 z-20 flex items-center gap-3 px-4 py-3 transition md:px-6 ${scrolled ? 'bg-canvas/95 backdrop-blur' : ''}`}>
      <div className="hidden gap-2 md:flex">
        <button onClick={() => navigate(-1)} aria-label="Go back" className="rounded-full bg-black/60 p-1.5 hover:bg-black"><ChevronLeft className="size-5" /></button>
        <button onClick={() => navigate(1)} aria-label="Go forward" className="rounded-full bg-black/60 p-1.5 hover:bg-black"><ChevronRight className="size-5" /></button>
      </div>
      <div className="relative max-w-md flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" />
        <input id="global-search" type="search" value={q} onChange={(e) => updateQuery(e.target.value)}
          onFocus={() => !onSearch && navigate('/search')}
          placeholder="What do you want to listen to?" aria-label="Search songs, artists, albums and playlists"
          className="w-full rounded-full border border-transparent bg-elevated py-2.5 pl-10 pr-4 text-sm placeholder:text-muted hover:border-line focus:border-white focus:outline-none" />
      </div>
      <div className="ml-auto flex items-center gap-3">
        <span title={status === 'online' ? 'Live updates connected' : 'Live updates reconnecting'} className="hidden sm:block">
          {status === 'online' ? <Wifi className="size-4 text-accent" aria-label="Live updates connected" /> : <WifiOff className="size-4 text-subtle" aria-label="Live updates offline" />}
        </span>
        {!user?.is_premium && (
          <Link to="/premium" className="hidden rounded-full bg-white px-4 py-1.5 text-sm font-bold text-black hover:scale-105 sm:block">Explore Premium</Link>
        )}
        <div className="relative" ref={menuRef}>
          <button onClick={() => setMenu((m) => !m)} aria-label="Account menu" aria-expanded={menu}
            className="rounded-full bg-black/60 p-1 hover:scale-105">
            <Avatar user={user} />
          </button>
          {menu && (
            <div role="menu" className="absolute right-0 mt-2 w-56 rounded-md bg-elevated p-1 text-sm shadow-2xl ring-1 ring-line">
              <div className="border-b border-line px-3 py-2">
                <p className="truncate font-semibold">{user?.display_name}</p>
                <p className="truncate text-xs text-muted">{user?.email}</p>
                {user?.is_premium && <p className="mt-1 flex items-center gap-1 text-xs font-bold text-amber-300"><Crown className="size-3" /> Premium</p>}
              </div>
              <Link role="menuitem" to="/account" onClick={() => setMenu(false)} className="flex items-center gap-2 rounded px-3 py-2 hover:bg-hover"><Settings className="size-4" /> Account</Link>
              <Link role="menuitem" to="/premium" onClick={() => setMenu(false)} className="flex items-center gap-2 rounded px-3 py-2 hover:bg-hover"><Crown className="size-4" /> {user?.is_premium ? 'Your plan' : 'Upgrade to Premium'}</Link>
              {(can('analytics:view') || can('catalog:write')) && (
                <Link role="menuitem" to="/admin" onClick={() => setMenu(false)} className="flex items-center gap-2 rounded px-3 py-2 hover:bg-hover"><Shield className="size-4" /> Admin</Link>
              )}
              <button role="menuitem" onClick={() => { setMenu(false); logout().then(() => navigate('/login')) }}
                className="flex w-full items-center gap-2 rounded px-3 py-2 hover:bg-hover"><LogOut className="size-4" /> Log out</button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
