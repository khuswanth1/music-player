import { useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router'
import { Heart, Home, Languages, Library, Plus, Radio, Search, Shield, Trophy, Users } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useLibrary } from '../../context/LibraryContext'
import { useSession } from '../../context/SessionContext'
import { useToast } from '../../context/ToastContext'
import { Cover, Skeleton } from '../ui'

export function Logo({ className = '' }) {
  return (
    <Link to="/" className={`flex items-center gap-2 text-xl font-extrabold tracking-tight ${className}`}>
      <img src="/favicon.svg" alt="" className="size-8" /> Wavely
    </Link>
  )
}

const navClass = ({ isActive }) =>
  `flex items-center gap-4 rounded-md px-3 py-2 font-semibold transition ${isActive ? 'text-white' : 'text-muted hover:text-white'}`

export default function Sidebar() {
  const { can } = useAuth()
  const { playlists, playlistsLoading, createPlaylist } = useLibrary()
  const { active: session } = useSession()
  const toast = useToast()
  const navigate = useNavigate()
  const [creating, setCreating] = useState(false)

  const newPlaylist = async () => {
    setCreating(true)
    try {
      const pl = await createPlaylist({ name: `My Playlist #${playlists.filter((p) => p.track_count >= 0).length + 1}` })
      navigate(`/playlist/${pl.id}`)
    } catch (err) {
      toast.apiError(err)
    } finally {
      setCreating(false)
    }
  }

  return (
    <aside className="hidden w-72 shrink-0 flex-col gap-2 p-2 md:flex" aria-label="Main navigation">
      <nav className="rounded-lg bg-surface px-3 py-4">
        <Logo className="mb-4 px-3" />
        <NavLink to="/" end className={navClass}><Home className="size-6" /> Home</NavLink>
        <NavLink to="/search" className={navClass}><Search className="size-6" /> Search</NavLink>
        <NavLink to="/languages" className={navClass}><Languages className="size-6" /> Languages</NavLink>
        <NavLink to="/charts" className={navClass}><Trophy className="size-6" /> Charts</NavLink>
        <NavLink to="/sessions" className={navClass}>
          <Users className="size-6" /> Listen together
          {session && <span className="ml-auto size-2 rounded-full bg-accent" aria-label="Session active" />}
        </NavLink>
        {(can('analytics:view') || can('catalog:write')) && (
          <NavLink to="/admin" className={navClass}><Shield className="size-6" /> Admin</NavLink>
        )}
      </nav>
      <section className="flex min-h-0 flex-1 flex-col rounded-lg bg-surface" aria-label="Your library">
        <div className="flex items-center justify-between px-6 pb-2 pt-4">
          <NavLink to="/library" className={navClass}><Library className="size-6" /> Your Library</NavLink>
          <button onClick={newPlaylist} disabled={creating} aria-label="Create playlist" title="Create playlist"
            className="rounded-full p-1.5 text-muted hover:bg-hover hover:text-white disabled:opacity-50">
            <Plus className="size-5" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          <NavLink to="/collection/tracks" className={({ isActive }) => `flex items-center gap-3 rounded-md p-2 hover:bg-hover ${isActive ? 'bg-hover' : ''}`}>
            <div className="flex size-12 items-center justify-center rounded bg-gradient-to-br from-indigo-600 to-sky-300">
              <Heart className="size-5" fill="white" />
            </div>
            <div><p className="font-semibold">Liked Songs</p><p className="text-sm text-muted">Playlist</p></div>
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => `flex items-center gap-3 rounded-md p-2 hover:bg-hover ${isActive ? 'bg-hover' : ''}`}>
            <div className="flex size-12 items-center justify-center rounded bg-elevated"><Radio className="size-5 text-accent" /></div>
            <div><p className="font-semibold">Recently played</p><p className="text-sm text-muted">History</p></div>
          </NavLink>
          {playlistsLoading && [0, 1, 2].map((i) => <div key={i} className="flex gap-3 p-2"><Skeleton className="size-12" /><div className="flex-1 space-y-2 pt-1"><Skeleton className="h-3 w-2/3" /><Skeleton className="h-3 w-1/3" /></div></div>)}
          {playlists.map((p) => (
            <NavLink key={p.id} to={`/playlist/${p.id}`} className={({ isActive }) => `flex items-center gap-3 rounded-md p-2 hover:bg-hover ${isActive ? 'bg-hover' : ''}`}>
              <Cover src={p.cover_url} seed={p.id} alt="" className="size-12" rounded="rounded" />
              <div className="min-w-0">
                <p className="truncate font-semibold">{p.name}</p>
                <p className="truncate text-sm text-muted">{p.is_collaborative ? 'Collaborative' : 'Playlist'} · {p.owner.display_name}</p>
              </div>
            </NavLink>
          ))}
        </div>
        <Link to="/sources" className="border-t border-line px-6 py-3 text-xs text-subtle hover:text-white">Sources &amp; licenses</Link>
      </section>
    </aside>
  )
}
