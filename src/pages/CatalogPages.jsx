import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { BadgeCheck, Heart, Shuffle } from 'lucide-react'
import { catalogApi, libraryApi, worldApi } from '../api/endpoints'
import { AlbumCard, ArtistCard, CardGrid, CardRow, PlayFab } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import TrackList from '../components/TrackList'
import { isUnavailable } from '../lib/tracks'
import { Button, CardGridSkeleton, Cover, EmptyState, ErrorState, PageSkeleton, TrackListSkeleton } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { formatLongDuration, plural } from '../lib/format'
import { languageName, useLanguages } from '../lib/languages'

/** Big header shared by album, playlist, artist and liked-songs pages. */
export function CollectionHeader({ image, seed, kicker, title, children, round = false, color = 'from-indigo-700' }) {
  return (
    <div className={`-mt-16 flex flex-col gap-6 bg-gradient-to-b ${color} to-transparent px-4 pb-6 pt-24 sm:flex-row sm:items-end md:px-6`}>
      <Cover src={image} seed={seed} alt={title} rounded={round ? 'rounded-full' : 'rounded-md'} className="size-44 shrink-0 shadow-2xl md:size-56" />
      <div className="min-w-0">
        <p className="text-sm font-semibold">{kicker}</p>
        <h1 className="mt-1 break-words text-4xl font-black tracking-tight md:text-6xl">{title}</h1>
        <div className="mt-4 flex flex-wrap items-center gap-1 text-sm text-zinc-200">{children}</div>
      </div>
    </div>
  )
}

export function usePlayContext(kind, id, name, songs) {
  const p = usePlayer()
  const active = p.context?.type === kind && p.context?.id === id
  return {
    playing: active && p.isPlaying,
    play: () => (active ? p.toggle() : songs.length && p.playList(songs, 0, { type: kind, id, name })),
    shuffle: () => {
      if (!p.shuffle) p.toggleShuffle()
      p.playList(songs, Math.floor(Math.random() * songs.length), { type: kind, id, name })
    },
  }
}

export function AlbumPage() {
  const { id } = useParams()
  const toast = useToast()
  const { data: album, error, loading, reload, setData } = useApi(() => catalogApi.album(id), [id])
  // Only tracks that can be played here are shown: a 30-second preview isn't the song.
  const songs = (album?.songs || []).filter((s) => !isUnavailable(s))
  const hidden = (album?.songs?.length || 0) - songs.length
  const controls = usePlayContext('album', id, album?.title, songs)

  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading) return <PageSkeleton />

  const toggleSave = async () => {
    try {
      await (album.is_saved ? libraryApi.unsaveAlbum(id) : libraryApi.saveAlbum(id))
      setData((a) => ({ ...a, is_saved: !a.is_saved }))
      toast.success(album.is_saved ? 'Removed from Your Library' : 'Saved to Your Library')
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <div>
      <CollectionHeader image={album.cover_url} seed={album.id} kicker={album.album_type === 'ep' ? 'EP' : album.album_type[0].toUpperCase() + album.album_type.slice(1)} title={album.title}>
        <Link to={`/artist/${album.artist.id}`} className="font-bold hover:underline">{album.artist.name}</Link>
        <span>{album.release_date ? `· ${new Date(album.release_date).getFullYear()} ` : ''}· {plural(songs.length, 'song')}{songs.length ? `, ${formatLongDuration(songs.reduce((n, s) => n + s.duration_ms, 0))}` : ''}</span>
      </CollectionHeader>
      <div className="flex items-center gap-6 px-4 py-4 md:px-6">
        <PlayFab onClick={controls.play} playing={controls.playing} label={`Play ${album.title}`} className="size-14" />
        <button onClick={toggleSave} aria-pressed={album.is_saved} aria-label={album.is_saved ? 'Remove from Your Library' : 'Save to Your Library'}
          className={album.is_saved ? 'text-accent' : 'text-muted hover:text-white'}>
          <Heart className="size-8" fill={album.is_saved ? 'currentColor' : 'none'} />
        </button>
        <button onClick={controls.shuffle} aria-label="Shuffle play" className="text-muted hover:text-white"><Shuffle className="size-7" /></button>
      </div>
      <div className="px-2 md:px-4">
        {songs.length === 0
          ? <EmptyState title="No complete recordings of this album here">The sources only supply 30-second previews or metadata for it. Try searching for the artist, or browse albums that can be played.</EmptyState>
          : <TrackList items={songs.map((song) => ({ song }))} context={{ type: 'album', id, name: album.title }} showAlbum={false} showCover={false} />}
        {hidden > 0 && songs.length > 0 && <p className="mt-2 px-3 text-xs text-subtle">{hidden} track{hidden === 1 ? '' : 's'} not shown: only a 30-second preview exists.</p>}
        {album.release_date && <p className="mt-6 px-3 text-xs text-muted">Released {new Date(album.release_date).toLocaleDateString(undefined, { dateStyle: 'long' })}</p>}
        {album.source !== 'local' && album.source_url && (
          <p className="mt-2 px-3 text-xs text-muted">
            From <a href={album.source_url} target="_blank" rel="noopener noreferrer" className="underline hover:text-white">the source</a>. Each track keeps its own license — see “Credits &amp; license” in its menu.
          </p>
        )}
      </div>
    </div>
  )
}

export function ArtistPage() {
  const { id } = useParams()
  const toast = useToast()
  const languages = useLanguages()
  const artist = useApi(() => worldApi.artistProfile(id), [id])
  const [showAll, setShowAll] = useState(false)
  const songs = artist.data?.top_songs || []
  const controls = usePlayContext('artist', id, artist.data?.name, songs)

  if (artist.error) return <ErrorState error={artist.error} onRetry={artist.reload} />
  if (artist.loading) return <PageSkeleton />
  const a = artist.data

  const toggleFollow = async () => {
    try {
      await (a.is_followed ? libraryApi.unfollow(id) : libraryApi.follow(id))
      artist.setData((x) => ({ ...x, is_followed: !x.is_followed, follower_count: x.follower_count + (x.is_followed ? -1 : 1) }))
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <div>
      <CollectionHeader image={a.image_url || a.image_fallback} seed={a.id} round title={a.name} color="from-rose-800"
        kicker={a.verified ? <span className="flex items-center gap-1"><BadgeCheck className="size-5 text-sky-400" /> Verified artist</span> : 'Artist'}>
        <span>
          {plural(a.follower_count, 'follower')} · {plural(a.song_count, 'song')} ({a.playable_count} playable)
          · {a.languages.length ? a.languages.map((c) => languageName(languages, c)).join(', ') : 'Language unknown'}
          · {a.country || 'Country unknown'}
        </span>
      </CollectionHeader>
      <div className="flex items-center gap-6 px-4 py-4 md:px-6">
        <PlayFab onClick={controls.play} playing={controls.playing} label={`Play ${a.name}`} className="size-14" />
        <Button variant="outline" onClick={toggleFollow} aria-pressed={a.is_followed}>{a.is_followed ? 'Following' : 'Follow'}</Button>
        {a.source !== 'local' && a.source_url && (
          <a href={a.source_url} target="_blank" rel="noopener noreferrer" className="text-sm text-muted hover:text-white hover:underline">View at {a.source}</a>
        )}
      </div>
      {a.providers.some((p) => p.status !== 'ok') && <ProviderStatusList providers={a.providers} className="px-4 pb-3 md:px-6" />}
      <section className="px-2 md:px-4">
        <h2 className="mb-3 px-2 text-2xl font-bold">Available songs</h2>
        {songs.length === 0 ? <p className="px-3 text-muted">No songs from this artist are in the catalog yet.</p> : (
          <>
            <TrackList items={songs.slice(0, showAll ? 10 : 5).map((song) => ({ song }))} context={{ type: 'artist', id, name: a.name }} />
            {songs.length > 5 && <button onClick={() => setShowAll((s) => !s)} className="mt-2 px-3 text-sm font-bold text-muted hover:text-white">{showAll ? 'Show less' : 'See more'}</button>}
          </>
        )}
      </section>
      {a.albums.length > 0 && (
        <section className="mt-10 px-4 md:px-6">
          <h2 className="mb-4 text-2xl font-bold">Albums</h2>
          <CardRow>{a.albums.map((al) => <AlbumCard key={al.id} album={al} />)}</CardRow>
        </section>
      )}
      {a.singles.length > 0 && (
        <section className="mt-10 px-4 md:px-6">
          <h2 className="mb-4 text-2xl font-bold">Singles</h2>
          <CardRow>{a.singles.map((al) => <AlbumCard key={al.id} album={al} />)}</CardRow>
        </section>
      )}
      {a.release_history.length > 0 && (
        <section className="mt-10 px-4 md:px-6">
          <h2 className="mb-3 text-2xl font-bold">Release history</h2>
          <ul className="flex flex-wrap gap-2" aria-label="Releases by year">
            {a.release_history.map((y) => (
              <li key={y.year} className="rounded-md bg-elevated px-3 py-2 text-sm">
                <span className="font-bold">{y.year}</span> <span className="text-muted">· {plural(y.albums, 'release')}, {plural(y.songs, 'song')}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {a.related.length > 0 && (
        <section className="mt-10 px-4 md:px-6">
          <h2 className="mb-1 text-2xl font-bold">Related artists</h2>
          <p className="mb-3 text-xs text-subtle">{a.related_basis}</p>
          <CardRow>{a.related.map((r) => <ArtistCard key={r.id} artist={r} />)}</CardRow>
        </section>
      )}
      {a.bio && (
        <section className="mt-10 px-4 md:px-6">
          <h2 className="mb-3 text-2xl font-bold">About</h2>
          <p className="max-w-2xl text-muted">{a.bio}</p>
        </section>
      )}
    </div>
  )
}

export function GenrePage() {
  const { slug } = useParams()
  const genre = useApi(() => catalogApi.genre(slug), [slug])
  const songs = useApi((signal) => worldApi.tracks({ genre: slug, page: 1, page_size: 50 }, signal), [slug])
  const albums = useApi(() => catalogApi.albums({ genre: slug, page_size: 12 }), [slug])
  const [more, setMore] = useState({ slug: '', items: [], page: 1, busy: false })
  const extra = more.slug === slug ? more : { items: [], page: 1, busy: false }
  const list = [...(songs.data?.items || []), ...extra.items]
  const total = songs.data?.total || 0
  const loadMore = async () => {
    setMore({ ...extra, slug, busy: true })
    try {
      const next = await worldApi.tracks({ genre: slug, page: extra.page + 1, page_size: 50 })
      setMore({ slug, items: [...extra.items, ...next.items], page: extra.page + 1, busy: false })
    } catch (err) {
      setMore({ ...extra, slug, busy: false })
      toast.apiError(err)
    }
  }
  const controls = usePlayContext('genre', slug, genre.data?.name, list)
  const toast = useToast()
  const [page, setPage] = useState(0) // each press reaches one page deeper into the music sources
  const [fetching, setFetching] = useState(false)

  const findMore = async () => {
    setFetching(true)
    try {
      const res = await worldApi.fetchGenre(slug, page)
      setPage(page + 1)
      setMore({ slug: '', items: [], page: 1, busy: false })
      await Promise.all([songs.reload({ silent: true }), albums.reload({ silent: true })])
      toast.info(res.imported ? `Added ${res.imported} new tracks` : 'No new tracks on this page; try again for the next one')
    } catch (err) {
      toast.apiError(err)
    } finally {
      setFetching(false)
    }
  }

  if (genre.error) return <ErrorState error={genre.error} onRetry={genre.reload} />
  return (
    <div>
      <div className="-mt-16 px-4 pb-8 pt-28 md:px-6" style={{ background: `linear-gradient(${genre.data?.color || '#333'}, transparent)` }}>
        <p className="text-sm font-semibold">Genre</p>
        <h1 className="text-5xl font-black md:text-7xl">{genre.data?.name || '…'}</h1>
      </div>
      <div className="flex items-center gap-6 px-4 pb-4 md:px-6">
        <PlayFab onClick={controls.play} playing={controls.playing} label="Play genre" className="size-14" />
        <Button variant="outline" onClick={findMore} loading={fetching}>Find more {genre.data?.name} from the sources</Button>
      </div>
      <section className="px-2 md:px-4">
        <h2 className="mb-3 px-2 text-2xl font-bold">Popular {genre.data?.name} tracks</h2>
        {songs.loading ? <TrackListSkeleton /> : (
          <>
            <TrackList items={list.map((song) => ({ song }))} context={{ type: 'genre', id: slug, name: genre.data?.name }} />
            <p className="mt-3 px-3 text-xs text-subtle" role="status">Showing {list.length} of {total} tracks</p>
            {list.length < total && (
              <div className="mt-3 flex justify-center"><Button variant="outline" onClick={loadMore} loading={extra.busy}>Load more tracks</Button></div>
            )}
          </>
        )}
      </section>
      <section className="mt-10 px-4 md:px-6">
        <h2 className="mb-4 text-2xl font-bold">Albums</h2>
        {albums.loading ? <CardGridSkeleton /> : <CardGrid>{albums.data.items.map((a) => <AlbumCard key={a.id} album={a} />)}</CardGrid>}
      </section>
    </div>
  )
}
