import { useState } from 'react'
import { Link } from 'react-router'
import { Pencil, Plus, Trash2, Upload } from 'lucide-react'
import { adminApi, catalogApi } from '../../api/endpoints'
import { Badge, Button, Cover, ErrorState, Field, Modal, Spinner, inputClass } from '../../components/ui'
import { useToast } from '../../context/ToastContext'
import { useApi } from '../../hooks/useApi'
import { formatDate, formatDuration, formatNumber } from '../../lib/format'
import { Pagination, Table } from './AdminLayout'

const fileClass = 'text-sm text-muted file:mr-3 file:rounded-full file:border-0 file:bg-white file:px-4 file:py-1.5 file:font-bold file:text-black'

function useRefs() {
  const artists = useApi(() => catalogApi.artists({ page_size: 100 }), [])
  const albums = useApi(() => catalogApi.albums({ page_size: 100, sort: 'title' }), [])
  const genres = useApi(() => catalogApi.genres(), [])
  return { artists: artists.data?.items || [], albums: albums.data?.items || [], genres: genres.data || [],
    reload: () => { artists.reload(); albums.reload(); genres.reload() } }
}

function useAction() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const run = async (fn, success) => {
    setBusy(true)
    try {
      const result = await fn()
      if (success) toast.success(success)
      return result ?? true
    } catch (err) {
      toast.error(err.details?.[0] ? `${err.details[0].field}: ${err.details[0].message}` : err.message)
      return null
    } finally {
      setBusy(false)
    }
  }
  return { busy, run }
}

// --- songs -----------------------------------------------------------------------------

function SongForm({ song, refs, onDone }) {
  const { busy, run } = useAction()
  const [f, setF] = useState({
    title: song?.title || '', artist_id: song?.artist.id || '', album_id: song?.album?.id || '', genre_id: song?.genre?.id || '',
    track_number: song?.track_number || '', explicit: song?.explicit || false, is_premium: song?.is_premium || false,
    is_published: song?.is_published ?? true,
  })
  const [file, setFile] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    const payload = { ...f, album_id: f.album_id || null, genre_id: f.genre_id ? Number(f.genre_id) : null,
      track_number: f.track_number ? Number(f.track_number) : null }
    const ok = song
      ? await run(async () => {
        await adminApi.updateSong(song.id, payload)
        if (file) await adminApi.replaceAudio(song.id, file)
      }, 'Song updated')
      : await run(() => adminApi.createSong({ ...payload, file }), 'Song uploaded')
    if (ok) onDone()
  }
  return (
    <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><Field label="Title"><input required maxLength={200} className={inputClass} value={f.title} onChange={set('title')} /></Field></div>
      <Field label="Artist"><select required className={inputClass} value={f.artist_id} onChange={set('artist_id')}>
        <option value="">Select…</option>{refs.artists.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
      <Field label="Album"><select className={inputClass} value={f.album_id} onChange={set('album_id')}>
        <option value="">Single (no album)</option>{refs.albums.filter((a) => !f.artist_id || a.artist.id === f.artist_id).map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}</select></Field>
      <Field label="Genre"><select className={inputClass} value={f.genre_id} onChange={set('genre_id')}>
        <option value="">None</option>{refs.genres.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></Field>
      <Field label="Track number"><input type="number" min={1} max={999} className={inputClass} value={f.track_number} onChange={set('track_number')} /></Field>
      <div className="sm:col-span-2">
        <Field label={song ? 'Replace audio (optional)' : 'Audio file'} hint="MP3, OGG, FLAC, WAV or M4A, up to 50 MB. Duration is read from the file. Only upload audio you have the rights to.">
          <input type="file" required={!song} accept="audio/*,.mp3,.ogg,.flac,.wav,.m4a" onChange={(e) => setFile(e.target.files[0])} className={fileClass} />
        </Field>
      </div>
      <div className="flex flex-wrap gap-5 text-sm sm:col-span-2">
        {[['is_published', 'Published'], ['is_premium', 'Premium only'], ['explicit', 'Explicit']].map(([k, label]) => (
          <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={f[k]} onChange={set(k)} className="size-4 accent-[var(--color-accent)]" />{label}</label>
        ))}
      </div>
      <div className="flex justify-end gap-2 sm:col-span-2"><Button type="submit" loading={busy}>{song ? 'Save' : <><Upload className="size-4" /> Upload</>}</Button></div>
    </form>
  )
}

function SongsTab({ refs }) {
  const [page, setPage] = useState(1)
  const [modal, setModal] = useState(null) // 'new' | song
  const { run } = useAction()
  const { data, error, loading, reload } = useApi(() => catalogApi.songs({ page, page_size: 20, sort: 'newest', include_unpublished: true }), [page])
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <>
      <div className="mb-4 flex justify-end"><Button onClick={() => setModal('new')}><Plus className="size-4" /> Upload song</Button></div>
      {loading ? <Spinner /> : (
        <>
          <Table head={['Title', 'Artist', 'Album', 'Length', 'Plays', 'Status', '']}>
            {data.items.map((s) => (
              <tr key={s.id} className="hover:bg-surface">
                <td className="px-4 py-2 font-medium">{s.title}</td>
                <td className="px-4 py-2 text-muted">{s.artist.name}</td>
                <td className="px-4 py-2 text-muted">{s.album?.title || '—'}</td>
                <td className="px-4 py-2 tabular-nums text-muted">{formatDuration(s.duration_ms)}</td>
                <td className="px-4 py-2 tabular-nums text-muted">{formatNumber(s.play_count)}</td>
                <td className="space-x-1 px-4 py-2">{s.is_published ? <Badge tone="accent">live</Badge> : <Badge>draft</Badge>}{s.is_premium && <Badge tone="warn">premium</Badge>}</td>
                <td className="whitespace-nowrap px-4 py-2 text-right">
                  <button onClick={() => setModal(s)} aria-label={`Edit ${s.title}`} className="p-1 text-muted hover:text-white"><Pencil className="size-4" /></button>
                  <button aria-label={`Delete ${s.title}`} className="p-1 text-muted hover:text-danger"
                    onClick={async () => window.confirm(`Delete "${s.title}" and its audio?`) && (await run(() => adminApi.deleteSong(s.id), 'Song deleted')) && reload()}>
                    <Trash2 className="size-4" /></button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pages={data.pages} total={data.total} onChange={setPage} />
        </>
      )}
      <Modal wide open={Boolean(modal)} onClose={() => setModal(null)} title={modal === 'new' ? 'Upload song' : 'Edit song'}>
        {modal && <SongForm song={modal === 'new' ? null : modal} refs={refs} onDone={() => { setModal(null); reload() }} />}
      </Modal>
    </>
  )
}

// --- albums ----------------------------------------------------------------------------

function AlbumsTab({ refs }) {
  const [modal, setModal] = useState(null)
  const { busy, run } = useAction()
  const [f, setF] = useState({})
  const [file, setFile] = useState(null)
  const open = (album) => {
    setF(album ? { title: album.title, artist_id: album.artist.id, album_type: album.album_type, release_date: album.release_date, is_featured: album.is_featured }
      : { title: '', artist_id: '', album_type: 'album', release_date: new Date().toISOString().slice(0, 10), is_featured: false })
    setFile(null)
    setModal(album || 'new')
  }
  const submit = async (e) => {
    e.preventDefault()
    const ok = await run(async () => {
      const album = modal === 'new' ? await adminApi.createAlbum(f) : await adminApi.updateAlbum(modal.id, f)
      if (file) await adminApi.albumCover(album.id, file)
    }, modal === 'new' ? 'Album created' : 'Album updated')
    if (ok) { setModal(null); refs.reload() }
  }
  return (
    <>
      <div className="mb-4 flex justify-end"><Button onClick={() => open(null)}><Plus className="size-4" /> New album</Button></div>
      <Table head={['', 'Title', 'Artist', 'Type', 'Released', '']} empty={!refs.albums.length && 'No albums yet.'}>
        {refs.albums.map((a) => (
          <tr key={a.id} className="hover:bg-surface">
            <td className="w-14 px-4 py-2"><Cover src={a.cover_url} seed={a.id} alt="" className="size-10" rounded="rounded" /></td>
            <td className="px-4 py-2 font-medium"><Link to={`/album/${a.id}`} className="hover:underline">{a.title}</Link> {a.is_featured && <Badge tone="accent">featured</Badge>}</td>
            <td className="px-4 py-2 text-muted">{a.artist.name}</td>
            <td className="px-4 py-2 text-muted">{a.album_type}</td>
            <td className="px-4 py-2 text-muted">{formatDate(a.release_date)}</td>
            <td className="whitespace-nowrap px-4 py-2 text-right">
              <button onClick={() => open(a)} aria-label={`Edit ${a.title}`} className="p-1 text-muted hover:text-white"><Pencil className="size-4" /></button>
              <button aria-label={`Delete ${a.title}`} className="p-1 text-muted hover:text-danger"
                onClick={async () => window.confirm(`Delete "${a.title}"? Its songs remain as singles.`) && (await run(() => adminApi.deleteAlbum(a.id), 'Album deleted')) && refs.reload()}><Trash2 className="size-4" /></button>
            </td>
          </tr>
        ))}
      </Table>
      <Modal open={Boolean(modal)} onClose={() => setModal(null)} title={modal === 'new' ? 'New album' : 'Edit album'}>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Title"><input required maxLength={200} className={inputClass} value={f.title || ''} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Artist"><select required className={inputClass} value={f.artist_id || ''} onChange={(e) => setF({ ...f, artist_id: e.target.value })}>
            <option value="">Select…</option>{refs.artists.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Type"><select className={inputClass} value={f.album_type} onChange={(e) => setF({ ...f, album_type: e.target.value })}>
              {['album', 'single', 'ep', 'compilation'].map((t) => <option key={t}>{t}</option>)}</select></Field>
            <Field label="Release date"><input type="date" required className={inputClass} value={f.release_date || ''} onChange={(e) => setF({ ...f, release_date: e.target.value })} /></Field>
          </div>
          <Field label="Cover" hint="JPEG, PNG or WebP"><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files[0])} className={fileClass} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(f.is_featured)} onChange={(e) => setF({ ...f, is_featured: e.target.checked })} className="size-4 accent-[var(--color-accent)]" /> Featured on the home page</label>
          <div className="flex justify-end"><Button type="submit" loading={busy}>Save</Button></div>
        </form>
      </Modal>
    </>
  )
}

// --- artists ---------------------------------------------------------------------------

function ArtistsTab({ refs }) {
  const [modal, setModal] = useState(null)
  const { busy, run } = useAction()
  const [f, setF] = useState({})
  const [file, setFile] = useState(null)
  const open = (a) => {
    setF(a ? { name: a.name, bio: a.bio, verified: a.verified } : { name: '', bio: '', verified: false })
    setFile(null)
    setModal(a || 'new')
  }
  const submit = async (e) => {
    e.preventDefault()
    const ok = await run(async () => {
      const artist = modal === 'new' ? await adminApi.createArtist(f) : await adminApi.updateArtist(modal.id, f)
      if (file) await adminApi.artistImage(artist.id, file)
    }, modal === 'new' ? 'Artist created' : 'Artist updated')
    if (ok) { setModal(null); refs.reload() }
  }
  return (
    <>
      <div className="mb-4 flex justify-end"><Button onClick={() => open(null)}><Plus className="size-4" /> New artist</Button></div>
      <Table head={['', 'Name', 'Verified', '']} empty={!refs.artists.length && 'No artists yet.'}>
        {refs.artists.map((a) => (
          <tr key={a.id} className="hover:bg-surface">
            <td className="w-14 px-4 py-2"><Cover src={a.image_url} seed={a.id} alt="" className="size-10" rounded="rounded-full" /></td>
            <td className="px-4 py-2 font-medium"><Link to={`/artist/${a.id}`} className="hover:underline">{a.name}</Link></td>
            <td className="px-4 py-2 text-muted">{a.verified ? 'Yes' : 'No'}</td>
            <td className="whitespace-nowrap px-4 py-2 text-right">
              <button onClick={() => open(a)} aria-label={`Edit ${a.name}`} className="p-1 text-muted hover:text-white"><Pencil className="size-4" /></button>
              <button aria-label={`Delete ${a.name}`} className="p-1 text-muted hover:text-danger"
                onClick={async () => window.confirm(`Delete "${a.name}"?`) && (await run(() => adminApi.deleteArtist(a.id), 'Artist deleted')) && refs.reload()}><Trash2 className="size-4" /></button>
            </td>
          </tr>
        ))}
      </Table>
      <Modal open={Boolean(modal)} onClose={() => setModal(null)} title={modal === 'new' ? 'New artist' : 'Edit artist'}>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Name"><input required maxLength={120} className={inputClass} value={f.name || ''} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Bio"><textarea rows={4} maxLength={5000} className={inputClass} value={f.bio || ''} onChange={(e) => setF({ ...f, bio: e.target.value })} /></Field>
          <Field label="Image"><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files[0])} className={fileClass} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(f.verified)} onChange={(e) => setF({ ...f, verified: e.target.checked })} className="size-4 accent-[var(--color-accent)]" /> Verified</label>
          <div className="flex justify-end"><Button type="submit" loading={busy}>Save</Button></div>
        </form>
      </Modal>
    </>
  )
}

// --- genres ----------------------------------------------------------------------------

function GenresTab({ refs }) {
  const { busy, run } = useAction()
  const [name, setName] = useState('')
  const [color, setColor] = useState('#3ee6a8')
  return (
    <>
      <form className="mb-4 flex flex-wrap items-end gap-3" onSubmit={async (e) => {
        e.preventDefault()
        if (await run(() => adminApi.createGenre({ name, color }), 'Genre created')) { setName(''); refs.reload() }
      }}>
        <Field label="New genre"><input required maxLength={60} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Color"><input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="h-10 w-16 rounded bg-surface" /></Field>
        <Button type="submit" loading={busy}><Plus className="size-4" /> Add</Button>
      </form>
      <Table head={['Genre', 'Color', '']}>
        {refs.genres.map((g) => (
          <tr key={g.id} className="hover:bg-surface">
            <td className="px-4 py-2 font-medium">{g.name}</td>
            <td className="px-4 py-2"><input type="color" aria-label={`Color for ${g.name}`} defaultValue={g.color}
              onBlur={(e) => e.target.value !== g.color && run(() => adminApi.updateGenre(g.id, { color: e.target.value }), 'Color saved').then(refs.reload)} className="h-8 w-12 rounded bg-surface" /></td>
            <td className="px-4 py-2 text-right">
              <button aria-label={`Delete ${g.name}`} className="p-1 text-muted hover:text-danger"
                onClick={async () => window.confirm(`Delete "${g.name}"? Songs keep playing but lose this genre.`) && (await run(() => adminApi.deleteGenre(g.id), 'Genre deleted')) && refs.reload()}><Trash2 className="size-4" /></button>
            </td>
          </tr>
        ))}
      </Table>
    </>
  )
}

export default function CatalogAdmin() {
  const [tab, setTab] = useState('songs')
  const refs = useRefs()
  const tabs = { songs: SongsTab, albums: AlbumsTab, artists: ArtistsTab, genres: GenresTab }
  const Active = tabs[tab]
  return (
    <div>
      <div className="mb-5 flex gap-2">
        {Object.keys(tabs).map((t) => (
          <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t}
            className={`rounded-full px-4 py-1.5 text-sm font-semibold capitalize ${tab === t ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>{t}</button>
        ))}
      </div>
      <Active refs={refs} />
    </div>
  )
}
