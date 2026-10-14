import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { Check, Copy, FolderLock, Globe2, Heart, ImagePlus, Lock, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { privateAlbumApi } from '../api/endpoints'
import { CardGrid, MediaCard } from '../components/Cards'
import TrackList from '../components/TrackList'
import { Button, CardGridSkeleton, EmptyState, ErrorState, Field, Modal, PageSkeleton, inputClass, selectClass } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { formatLongDuration, plural } from '../lib/format'
import { CollectionHeader } from './CatalogPages'

const SORTS = [['updated', 'Recently updated'], ['created', 'Recently created'], ['name', 'Name'], ['tracks', 'Most tracks']]

function AlbumForm({ initial, onSubmit, onClose, submitLabel }) {
  const [name, setName] = useState(initial?.name || '')
  const [description, setDescription] = useState(initial?.description || '')
  const [isPublic, setPublic] = useState(initial?.is_public || false)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await onSubmit({ name: name.trim(), description, is_public: isPublic })
      onClose()
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required autoFocus className={inputClass} /></Field>
      <Field label="Description"><textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} rows={3} className={inputClass} /></Field>
      <label className="flex items-start gap-3 text-sm">
        <input type="checkbox" checked={isPublic} onChange={(e) => setPublic(e.target.checked)} className="mt-1 size-4 accent-emerald-500" />
        <span><span className="font-semibold">Anyone with the link can view this album</span>
          <span className="block text-muted">Off by default: only you can see a private album. Turning this off later stops existing links working.</span></span>
      </label>
      <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy} disabled={!name.trim()}>{submitLabel}</Button></div>
    </form>
  )
}

export function PrivateAlbumsPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const [sort, setSort] = useState('updated')
  const [favorites, setFavorites] = useState(false)
  const [creating, setCreating] = useState(false)
  const { data, loading, error, reload } = useApi(() => privateAlbumApi.list({ sort, favorites: favorites || undefined }), [sort, favorites])

  const create = async (values) => {
    try {
      const album = await privateAlbumApi.create(values)
      navigate(`/private-albums/${album.id}`)
    } catch (err) {
      toast.apiError(err)
      throw err
    }
  }

  return (
    <div className="px-4 md:px-6">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-extrabold tracking-tight">Private albums</h1>
        <Button onClick={() => setCreating(true)} className="ml-auto"><Plus className="size-4" /> New album</Button>
      </div>
      <p className="mb-5 max-w-2xl text-sm text-muted">Your own collections of tracks from the catalog. Only references are stored — never audio — and only you can see an album unless you make it public and share the link.</p>
      <div className="mb-5 flex flex-wrap items-center gap-2">
        <select aria-label="Sort albums" value={sort} onChange={(e) => setSort(e.target.value)} className={`${selectClass}`}>
          {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <button onClick={() => setFavorites(!favorites)} aria-pressed={favorites}
          className={`flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-semibold ${favorites ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>
          <Heart className="size-4" fill={favorites ? 'currentColor' : 'none'} /> Favorites
        </button>
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && <CardGridSkeleton />}
      {data && !loading && (data.length === 0
        ? <EmptyState icon={FolderLock} title={favorites ? 'No favorite albums' : 'No private albums yet'}>Create one, then add tracks from any track’s ⋯ menu.</EmptyState>
        : (
          <CardGrid>
            {data.map((a) => (
              <MediaCard key={a.id} to={`/private-albums/${a.id}`} image={a.cover_url} seed={a.id} title={`${a.is_favorite ? '♥ ' : ''}${a.name}`}
                subtitle={`${plural(a.track_count, 'track')} · ${a.is_public ? 'Shared by link' : 'Private'}`} />
            ))}
          </CardGrid>
        ))}
      <Modal open={creating} onClose={() => setCreating(false)} title="New private album">
        <AlbumForm onSubmit={create} onClose={() => setCreating(false)} submitLabel="Create" />
      </Modal>
    </div>
  )
}

export function PrivateAlbumPage({ shared = false }) {
  const { id, code } = useParams()
  const toast = useToast()
  const navigate = useNavigate()
  const { playList } = usePlayer()
  const fileRef = useRef(null)
  const [editing, setEditing] = useState(false)
  const [copied, setCopied] = useState(false)
  const { data: album, loading, error, reload, setData } = useApi(() => (shared ? privateAlbumApi.shared(code) : privateAlbumApi.get(id)), [id, code])

  if (error) return <ErrorState error={error} onRetry={reload} title={shared ? 'This shared album isn’t available' : "Couldn't load this album"} />
  if (loading) return <PageSkeleton />

  const run = async (fn, message) => {
    try {
      const next = await fn()
      if (next) setData(next)
      if (message) toast.success(message)
      return next
    } catch (err) {
      toast.apiError(err)
      throw err
    }
  }
  const songs = album.tracks.map((t) => t.song)
  const shareUrl = album.share_path ? `${window.location.origin}${album.share_path}` : null
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.info(shareUrl)
    }
  }

  return (
    <div>
      <CollectionHeader image={album.cover_url} seed={album.id} kicker={shared ? `Shared album by ${album.owner.display_name}` : album.is_public ? 'Private album · shared by link' : 'Private album'} title={album.name} color="from-teal-800">
        <span>{plural(album.track_count, 'track')}{album.total_duration_ms ? `, ${formatLongDuration(album.total_duration_ms)}` : ''}</span>
        {album.description && <span className="block w-full text-zinc-300">{album.description}</span>}
      </CollectionHeader>
      <div className="flex flex-wrap items-center gap-3 px-4 py-4 md:px-6">
        <Button onClick={() => songs.length && playList(songs, 0, { type: 'private-album', id: album.id, name: album.name })} disabled={!songs.length}>Play</Button>
        {album.is_owner && (
          <>
            <Button variant="outline" onClick={() => setEditing(true)}><Pencil className="size-4" /> Edit</Button>
            <Button variant="ghost" aria-pressed={album.is_favorite} onClick={() => run(() => privateAlbumApi.update(album.id, { is_favorite: !album.is_favorite }))}>
              <Heart className="size-4" fill={album.is_favorite ? 'currentColor' : 'none'} /> {album.is_favorite ? 'Favorite' : 'Mark favorite'}
            </Button>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden
              onChange={(e) => e.target.files[0] && run(() => privateAlbumApi.cover(album.id, e.target.files[0]), 'Cover updated')} />
            <Button variant="ghost" onClick={() => fileRef.current?.click()}><ImagePlus className="size-4" /> Cover</Button>
            <Button variant="ghost" onClick={async () => {
              if (!window.confirm(`Delete “${album.name}”? The tracks themselves aren't affected.`)) return
              await run(async () => { await privateAlbumApi.remove(album.id); return null }, 'Album deleted')
              navigate('/private-albums')
            }}><Trash2 className="size-4" /> Delete</Button>
          </>
        )}
      </div>
      {album.is_owner && (
        <div className="mx-4 mb-4 rounded-lg bg-elevated p-4 md:mx-6">
          <p className="flex items-center gap-2 text-sm font-semibold">{album.is_public ? <Globe2 className="size-4 text-accent" /> : <Lock className="size-4" />} {album.is_public ? 'Anyone with the link can view' : 'Only you can see this album'}</p>
          {shareUrl && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input readOnly value={shareUrl} aria-label="Share link" className={`${inputClass} max-w-lg flex-1`} onFocus={(e) => e.target.select()} />
              <Button variant="outline" onClick={copy}>{copied ? <Check className="size-4" /> : <Copy className="size-4" />} {copied ? 'Copied' : 'Copy'}</Button>
              <Button variant="ghost" onClick={() => window.confirm('The current link will stop working. Continue?') && run(() => privateAlbumApi.share(album.id), 'New link created')}>
                <RefreshCw className="size-4" /> New link
              </Button>
            </div>
          )}
        </div>
      )}
      <div className="px-2 md:px-4">
        {album.tracks.length === 0
          ? <EmptyState icon={FolderLock} title="No tracks yet">Open any track’s ⋯ menu and choose “Add to private album”. <Link to="/search" className="underline">Find something to add</Link>.</EmptyState>
          : (
            <TrackList items={album.tracks.map((t) => ({ key: t.id, song: t.song, addedAt: t.added_at,
              onRemove: album.is_owner ? () => run(() => privateAlbumApi.removeTrack(album.id, t.id)) : undefined }))}
            context={{ type: 'private-album', id: album.id, name: album.name }} showAdded />
          )}
      </div>
      <Modal open={editing} onClose={() => setEditing(false)} title="Edit album">
        <AlbumForm initial={album} submitLabel="Save" onClose={() => setEditing(false)}
          onSubmit={(values) => run(() => privateAlbumApi.update(album.id, values), 'Saved')} />
      </Modal>
    </div>
  )
}

export const SharedAlbumPage = () => <PrivateAlbumPage shared />
