import { useCallback, useEffect, useRef, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../../context/AuthContext'
import { usePlayer } from '../../context/PlayerContext'
import { SHORTCUTS, useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts'
import PlayerBar from '../player/PlayerBar'
import QueuePanel from '../player/QueuePanel'
import { Modal, Spinner } from '../ui'
import MobileNav from './MobileNav'
import Sidebar from './Sidebar'
import TopBar from './TopBar'

export function RequireAuth({ children }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') {
    return <div className="flex h-full items-center justify-center"><Spinner className="size-8 text-accent" /></div>
  }
  if (status !== 'authenticated') {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return children
}

export default function AppLayout() {
  const player = usePlayer()
  const navigate = useNavigate()
  const [queueOpen, setQueueOpen] = useState(false)
  const [help, setHelp] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const mainRef = useRef(null)
  const location = useLocation()

  // New page: start at the top (the scroll container is <main>, not the window).
  useEffect(() => {
    mainRef.current?.scrollTo(0, 0)
  }, [location.pathname])

  const focusSearch = useCallback(() => {
    navigate('/search')
    setTimeout(() => document.getElementById('global-search')?.focus(), 0)
  }, [navigate])
  const toggleQueue = useCallback(() => setQueueOpen((o) => !o), [])
  const openHelp = useCallback(() => setHelp(true), [])
  useKeyboardShortcuts(player, { onSearch: focusSearch, onToggleQueue: toggleQueue, onHelp: openHelp })

  return (
    <div className="flex h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2 focus:text-black">Skip to content</a>
      <div className="flex min-h-0 flex-1 md:gap-0">
        <Sidebar />
        <main id="main" ref={mainRef}
          onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 10)}
          className="relative min-w-0 flex-1 overflow-y-auto bg-gradient-to-b from-[#2b2b2b] via-surface to-surface bg-[length:100%_320px] bg-no-repeat bg-surface md:my-2 md:mr-2 md:rounded-lg">
          <TopBar scrolled={scrolled} />
          <div className="pb-10">
            <Outlet />
          </div>
        </main>
        {queueOpen && <div className="my-2 mr-2 hidden lg:flex"><QueuePanel onClose={() => setQueueOpen(false)} /></div>}
      </div>
      <PlayerBar onToggleQueue={toggleQueue} queueOpen={queueOpen} />
      <MobileNav />
      <Modal open={help} onClose={() => setHelp(false)} title="Keyboard shortcuts">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          {SHORTCUTS.map(([keys, label]) => (
            <div key={keys} className="contents">
              <dt><kbd className="rounded bg-hover px-2 py-0.5 font-mono text-xs">{keys}</kbd></dt>
              <dd className="text-muted">{label}</dd>
            </div>
          ))}
        </dl>
      </Modal>
    </div>
  )
}
