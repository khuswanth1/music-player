import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { Copy, Globe2, Heart, Link2, Lock, Pencil, Search, Shuffle, Trash2, UserMinus, Users } from 'lucide-react'
import { catalogApi, libraryApi, playlistApi } from '../api/endpoints'
import { PlayFab } from '../components/Cards'
import TrackList from '../components/TrackList'
import { Avatar, Button, Cover, EmptyState, ErrorState, Field, Modal, PageSkeleton, Spinner, inputClass } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useLibrary } from '../context/LibraryContext'
import { useChannel } from '../context/RealtimeContext'
import { useToast } from '../context/ToastContext'
import { useApi, useDebounce } from '../hooks/useApi'
import { formatDuration, formatLongDuration, plural } from '../lib/format'
import { CollectionHeader, usePlayContext } from './CatalogPages'

function EditModal({ playlist, open, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({ name: playlist.name, description: playlist.description, is_public: playlist.is_public,
    is_collaborative: playlist.is_collaborative })
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      let updated = await playlistApi.update(playlist.id, form)
      if (file) updated = await playlistApi.cover(playlist.id, file)
      onSaved(updated)
      onClose()
      toast.success('Playlist updated')
    } catch (err) {
      toast.apiError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Edit details">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name"><input required maxLength={120} className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Description"><textarea maxLength={1000} rows={3} className={inputClass} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label="Cover image" hint="JPEG, PNG or WebP, up to 5 MB">
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files[0])} className="text-sm text-muted file:mr-3 file:rounded-full file:border-0 file:bg-white file:px-4 file:py-1.5 file:font-bold file:text-black" />
        </Field>
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" checked={form.is_collaborative} onChange={(e) => setForm({ ...form, is_collaborative: e.target.checked, is_public: e.target.checked ? false : form.is_public })} className="size-4 accent-[var(--color-accent)]" />
          Collaborative — invited friends can add, remove and reorder songs (Premium)
        </label>
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" disabled={form.is_collaborative} checked={form.is_public} onChange={(e) => setForm({ ...form, is_public: e.target.checked })} className="size-4 accent-[var(--color-accent)]" />
          Public — anyone with the link can view it and it appears in search
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="white" loading={busy}>Save</Button>
        </div>
      </form>
    </Modal>
  )
}

function AddSongs({ playlist, onAdded }) {
  const [q, setQ] = useState('')
  const debounced = useDebounce(q.trim(), 250)
  const toast = useToast()
  const { data, loading } = useApi((signal) => debounced ? catalogApi.search({ q: debounced, type: 'song', page_size: 8 }, signal) : Promise.resolve(null), [debounced])
  const existing = new Set(playlist.tracks.map((t) => t.song.id))
  const add = async (song) => {
    try {
      onAdded(await playlistApi.addTracks(playlist.id, [song.id]))
      toast.success(`Added ${song.title}`)
    } catch (err) {
      toast.apiError(err)
    }
  }
  return (
    <section className="mt-10 border-t border-line px-3 pt-6">
      <h2 className="text-xl font-bold">Let&apos;s find something for your playlist</h2>
      <div className="relative mt-4 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search for songs" aria-label="Search for songs to add" className={`${inputClass} pl-9`} />
      </div>
      {loading && debounced && <Spinner className="mt-4 size-5" />}
      <div className="mt-3 space-y-1">
        {data?.songs?.items.map((song) => (
          <div key={song.id} className="flex items-center gap-3 rounded-md p-2 hover:bg-hover">
            <div className="min-w-0 flex-1"><p className="truncate font-semibold">{song.title}</p><p className="truncate text-sm text-muted">{song.artist.name}</p></div>
            <span className="text-sm text-muted">{formatDuration(song.duration_ms)}</span>
            <Button variant="outline" className="px-4 py-1" onClick={() => add(song)}>{existing.has(song.id) ? 'Add again' : 'Add'}</Button>
          </div>
        ))}
        {data?.songs?.total === 0 && <p className="text-sm text-muted">No songs match “{debounced}”.</p>}
      </div>
    </section>
  )
}

export default function PlaylistPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { refreshPlaylists } = useLibrary()
  const toast = useToast()
  const { data: pl, error, loading, reload, setData } = useApi(() => playlistApi.get(id), [id])
  const [editing, setEditing] = useState(false)
  const [sharing, setSharing] = useState(false)
  const [presence, setPresence] = useState([])
  const songs = pl?.tracks.map((t) => t.song) || []
  const controls = usePlayContext('playlist', id, pl?.name, songs)

  // Live collaboration: refetch on changes made by others, and show who's viewing.
  useChannel(pl ? `playlist:${id}` : null, (msg) => {
    if (msg.type === 'presence') setPresence(msg.users)
    if (msg.type === 'playlist.updated' && msg.by?.user_id !== user?.id) {
      reload({ silent: true })
      toast.info(`${msg.by.display_name} updated this playlist`)
    }
    if (msg.type === 'playlist.deleted') {
      toast.info('This playlist was deleted')
      navigate('/library')
    }
  })

  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading) return <PageSkeleton />

  const mutate = async (fn, success) => {
    try {
      setData(await fn())
      if (success) toast.success(success)
      refreshPlaylists()
    } catch (err) {
      toast.apiError(err)
      reload({ silent: true })
    }
  }

  const reorder = (from, to) => {
    // optimistic local move, then confirm with the server's order
    setData((p) => {
      const tracks = [...p.tracks]
      const [moved] = tracks.splice(from, 1)
      tracks.splice(to, 0, moved)
      return { ...p, tracks }
    })
    mutate(() => playlistApi.reorder(id, from, to))
  }

  const remove = async () => {
    if (!window.confirm(`Delete "${pl.name}"? This can't be undone.`)) return
    try {
      await playlistApi.remove(id)
      await refreshPlaylists()
      toast.success('Playlist deleted')
      navigate('/library')
    } catch (err) {
      toast.apiError(err)
    }
  }

  const toggleSave = () => mutate(async () => {
    await (pl.is_saved ? libraryApi.unsavePlaylist(id) : libraryApi.savePlaylist(id))
    return { ...pl, is_saved: !pl.is_saved }
  }, pl.is_saved ? 'Removed from Your Library' : 'Saved to Your Library')

  const shareUrl = `${window.location.origin}/playlist/${id}`
  const inviteUrl = pl.collab_invite_code ? `${window.location.origin}/playlist/${id}/join?code=${pl.collab_invite_code}` : null
  const copy = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`${label} copied`)
    } catch {
      toast.info(text, { duration: 10000 })
    }
  }
  const others = presence.filter((u) => u.user_id !== user?.id)

  return (
    <div>
      <CollectionHeader image={pl.cover_url} seed={pl.id} title={pl.name} color="from-emerald-800"
        kicker={<span className="flex items-center gap-2">{pl.is_collaborative ? 'Collaborative playlist' : pl.is_public ? 'Public playlist' : 'Private playlist'}
          {pl.is_public ? <Globe2 className="size-4" /> : <Lock className="size-4" />}</span>}>
        {pl.description && <p className="mb-2 w-full text-muted">{pl.description}</p>}
        <Avatar user={pl.owner} size="size-6" />
        <span className="font-bold">{pl.owner.display_name}</span>
        {pl.collaborators.length > 0 && <span>+ {plural(pl.collaborators.length, 'collaborator')}</span>}
        <span>· {plural(pl.track_count, 'song')}{pl.total_duration_ms ? `, ${formatLongDuration(pl.total_duration_ms)}` : ''}</span>
      </CollectionHeader>

      <div className="flex flex-wrap items-center gap-5 px-4 py-4 md:px-6">
        <PlayFab onClick={controls.play} playing={controls.playing} label={`Play ${pl.name}`} className="size-14" />
        <button onClick={controls.shuffle} disabled={!songs.length} aria-label="Shuffle play" className="text-muted hover:text-white disabled:opacity-40"><Shuffle className="size-7" /></button>
        {!pl.is_owner && (
          <button onClick={toggleSave} aria-pressed={pl.is_saved} aria-label={pl.is_saved ? 'Remove from Your Library' : 'Save to Your Library'}
            className={pl.is_saved ? 'text-accent' : 'text-muted hover:text-white'}><Heart className="size-8" fill={pl.is_saved ? 'currentColor' : 'none'} /></button>
        )}
        {pl.is_owner && <button onClick={() => setEditing(true)} aria-label="Edit details" className="text-muted hover:text-white"><Pencil className="size-6" /></button>}
        {(pl.is_public || inviteUrl) && <button onClick={() => setSharing(true)} aria-label="Share" className="text-muted hover:text-white"><Link2 className="size-6" /></button>}
        {pl.is_owner && <button onClick={remove} aria-label="Delete playlist" className="text-muted hover:text-danger"><Trash2 className="size-6" /></button>}
        {!pl.is_owner && pl.can_edit && (
          <Button variant="ghost" onClick={async () => {
            await playlistApi.removeCollaborator(id, user.id).catch(toast.apiError)
            await refreshPlaylists()
            navigate('/library')
          }}><UserMinus className="size-4" /> Leave</Button>
        )}
        {others.length > 0 && (
          <div className="ml-auto flex items-center gap-2 text-sm text-muted" aria-label="Also viewing">
            <span className="hidden sm:inline">Also here:</span>
            <div className="flex -space-x-2">{others.map((u) => <Avatar key={u.user_id} user={{ ...u, id: u.user_id }} size="size-7" />)}</div>
          </div>
        )}
      </div>

      <div className="px-2 md:px-4">
        {pl.tracks.length === 0 ? (
          <EmptyState title="This playlist is empty">{pl.can_edit ? 'Search below to add some songs.' : 'Check back later.'}</EmptyState>
        ) : (
          <TrackList showAdded context={{ type: 'playlist', id, name: pl.name }}
            onReorder={pl.can_edit ? reorder : undefined}
            items={pl.tracks.map((t) => ({ key: t.id, song: t.song, addedAt: t.added_at, addedBy: pl.is_collaborative ? t.added_by : null,
              onRemove: pl.can_edit ? () => mutate(() => playlistApi.removeTrack(id, t.id), 'Removed from playlist') : undefined }))} />
        )}
        {pl.can_edit && <AddSongs playlist={pl} onAdded={(updated) => { setData(updated); refreshPlaylists() }} />}
      </div>

      {editing && <EditModal open playlist={pl} onClose={() => setEditing(false)} onSaved={(p) => { setData(p); refreshPlaylists() }} />}
      <Modal open={sharing} onClose={() => setSharing(false)} title="Share playlist">
        <div className="space-y-5">
          {pl.is_public && (
            <div>
              <p className="mb-2 text-sm text-muted">Anyone with this link can listen.</p>
              <div className="flex gap-2"><input readOnly value={shareUrl} className={inputClass} aria-label="Share link" /><Button variant="white" onClick={() => copy(shareUrl, 'Link')}><Copy className="size-4" /></Button></div>
            </div>
          )}
          {inviteUrl && (
            <div>
              <p className="mb-2 flex items-center gap-2 text-sm text-muted"><Users className="size-4" /> Invite collaborators — they can add and reorder songs.</p>
              <div className="flex gap-2"><input readOnly value={inviteUrl} className={inputClass} aria-label="Invite link" /><Button variant="white" onClick={() => copy(inviteUrl, 'Invite link')}><Copy className="size-4" /></Button></div>
              <button onClick={() => mutate(() => playlistApi.regenerateInvite(id), 'New invite link created — the old one no longer works')}
                className="mt-2 text-xs text-muted underline hover:text-white">Reset invite link</button>
            </div>
          )}
          {pl.is_owner && pl.collaborators.length > 0 && (
            <div>
              <p className="mb-2 text-sm font-semibold">Collaborators</p>
              {pl.collaborators.map((c) => (
                <div key={c.id} className="flex items-center gap-3 py-1.5">
                  <Avatar user={c} size="size-7" /><span className="flex-1 text-sm">{c.display_name}</span>
                  <button onClick={() => playlistApi.removeCollaborator(id, c.id).then(() => reload({ silent: true })).catch(toast.apiError)}
                    className="text-xs text-muted hover:text-danger">Remove</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}

export function JoinPlaylistPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const toast = useToast()
  const { refreshPlaylists } = useLibrary()
  const [busy, setBusy] = useState(false)
  const join = async () => {
    setBusy(true)
    try {
      await playlistApi.join(id, params.get('code') || '')
      await refreshPlaylists()
      toast.success('You can now edit this playlist')
      navigate(`/playlist/${id}`, { replace: true })
    } catch (err) {
      toast.apiError(err)
      setBusy(false)
    }
  }
  return (
    <EmptyState icon={Users} title="You've been invited to collaborate" action={<Button loading={busy} onClick={join}>Join playlist</Button>}>
      Collaborators can add, remove and reorder songs. Changes show up for everyone in real time.
    </EmptyState>
  )
}

export function LibraryPage() {
  const { playlists } = useLibrary()
  const [filter, setFilter] = useState('all')
  const saved = useApi(() => libraryApi.savedPlaylists(), [])
  const albums = useApi(() => libraryApi.albums(), [])
  const artists = useApi(() => libraryApi.following(), [])
  const show = (k) => filter === 'all' || filter === k
  const Row = ({ to, image, seed, title, subtitle, round }) => (
    <Link to={to} className="flex items-center gap-3 rounded-md p-2 hover:bg-hover">
      <Cover src={image} seed={seed || title} alt="" className="size-14 shrink-0" rounded={round ? 'rounded-full' : 'rounded'} />
      <div className="min-w-0"><p className="truncate font-semibold">{title}</p><p className="truncate text-sm text-muted">{subtitle}</p></div>
    </Link>
  )
  return (
    <div className="px-4 md:px-6">
      <h1 className="mb-4 text-3xl font-extrabold">Your Library</h1>
      <div className="mb-6 flex gap-2">
        {[['all', 'All'], ['playlists', 'Playlists'], ['albums', 'Albums'], ['artists', 'Artists']].map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)} aria-pressed={filter === k}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${filter === k ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>{label}</button>
        ))}
      </div>
      <div className="grid gap-1 md:grid-cols-2">
        {show('playlists') && (
          <Link to="/collection/tracks" className="flex items-center gap-3 rounded-md p-2 hover:bg-hover">
            <div className="flex size-14 items-center justify-center rounded bg-gradient-to-br from-indigo-600 to-sky-300"><Heart className="size-6" fill="white" /></div>
            <div><p className="font-semibold">Liked Songs</p><p className="text-sm text-muted">Playlist</p></div>
          </Link>
        )}
        {show('playlists') && [...playlists, ...(saved.data || [])].map((p) => (
          <Row key={p.id} to={`/playlist/${p.id}`} image={p.cover_url} seed={p.id} title={p.name}
            subtitle={`${p.is_collaborative ? 'Collaborative' : 'Playlist'} · ${p.owner.display_name} · ${plural(p.track_count, 'song')}`} />
        ))}
        {show('albums') && albums.data?.map((a) => <Row key={a.id} to={`/album/${a.id}`} image={a.cover_url} title={a.title} subtitle={`Album · ${a.artist.name}`} />)}
        {show('artists') && artists.data?.map((a) => <Row key={a.id} to={`/artist/${a.id}`} image={a.image_url} title={a.name} subtitle="Artist" round />)}
      </div>
      {(saved.loading || albums.loading || artists.loading) && <Spinner className="mt-6 size-6" />}
      {show('albums') && albums.data?.length === 0 && filter === 'albums' && <EmptyState title="No saved albums yet">Tap the heart on any album to save it here.</EmptyState>}
      {show('artists') && artists.data?.length === 0 && filter === 'artists' && <EmptyState title="You're not following any artists">Follow artists to see them here.</EmptyState>}
    </div>
  )
}

export function LikedSongsPage() {
  const { user } = useAuth()
  const [page, setPage] = useState(1)
  const { data, error, loading, reload } = useApi(() => libraryApi.liked(page, 100), [page])
  const { isLiked } = useLibrary()
  const items = (data?.items || []).filter((i) => isLiked(i.song))
  const controls = usePlayContext('liked', 'liked', 'Liked Songs', items.map((i) => i.song))
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <div>
      <CollectionHeader kicker="Playlist" title="Liked Songs" seed="liked" color="from-indigo-700">
        <span className="font-bold">{user?.display_name}</span><span>· {plural(data?.total ?? 0, 'song')}</span>
      </CollectionHeader>
      <div className="px-4 py-4 md:px-6"><PlayFab onClick={controls.play} playing={controls.playing} label="Play Liked Songs" className="size-14" /></div>
      <div className="px-2 md:px-4">
        {loading ? <Spinner /> : items.length === 0 ? (
          <EmptyState icon={Heart} title="Songs you like will appear here">Save songs by tapping the heart icon.</EmptyState>
        ) : (
          <TrackList showAdded context={{ type: 'liked', id: 'liked', name: 'Liked Songs' }}
            items={items.map((i) => ({ key: i.song.id, song: i.song, addedAt: i.created_at }))} />
        )}
        {data?.pages > 1 && (
          <div className="mt-6 flex justify-center gap-3 text-sm">
            <Button variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="outline" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        )}
      </div>
    </div>
  )
}

export function HistoryPage() {
  const toast = useToast()
  const [page, setPage] = useState(1)
  const { data, error, loading, reload } = useApi(() => libraryApi.history(page), [page])
  if (error) return <ErrorState error={error} onRetry={reload} />
  const clear = async () => {
    if (!window.confirm('Clear your entire listening history?')) return
    try {
      await libraryApi.clearHistory()
      toast.success('Listening history cleared')
      reload()
    } catch (err) {
      toast.apiError(err)
    }
  }
  return (
    <div className="px-2 md:px-4">
      <div className="mb-6 flex items-end justify-between px-2">
        <div><h1 className="text-3xl font-extrabold">Recently played</h1><p className="text-sm text-muted">Everything you&apos;ve listened to, newest first.</p></div>
        {data?.total > 0 && <Button variant="outline" onClick={clear}>Clear history</Button>}
      </div>
      {loading ? <Spinner /> : data.total === 0 ? <EmptyState title="Nothing here yet">Play something and it will show up here.</EmptyState> : (
        <>
          <TrackList showAdded context={{ type: 'history', name: 'Recently played' }}
            items={data.items.map((h) => ({ key: h.id, song: h.song, addedAt: h.played_at }))} />
          {data.pages > 1 && (
            <div className="mt-6 flex justify-center gap-3">
              <Button variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</Button>
              <Button variant="outline" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Older</Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
