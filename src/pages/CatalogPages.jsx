import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { BadgeCheck, Heart, Shuffle } from 'lucide-react'
import { catalogApi, libraryApi } from '../api/endpoints'
import { AlbumCard, CardGrid, PlayFab } from '../components/Cards'
import TrackList from '../components/TrackList'
import { Button, CardGridSkeleton, Cover, ErrorState, PageSkeleton, TrackListSkeleton } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { formatLongDuration, formatNumber, plural } from '../lib/format'

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
  const songs = album?.songs || []
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
        <span>{album.release_date ? `· ${new Date(album.release_date).getFullYear()} ` : ''}· {plural(songs.length, 'song')}, {formatLongDuration(album.total_duration_ms)}</span>
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
        <TrackList items={songs.map((song) => ({ song }))} context={{ type: 'album', id, name: album.title }} showAlbum={false} showCover={false} />
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
  const artist = useApi(() => catalogApi.artist(id), [id])
  const top = useApi(() => catalogApi.artistTopSongs(id), [id])
  const albums = useApi(() => catalogApi.artistAlbums(id), [id])
  const [showAll, setShowAll] = useState(false)
  const songs = top.data || []
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
      <CollectionHeader image={a.image_url} seed={a.id} round title={a.name} color="from-rose-800"
        kicker={a.verified ? <span className="flex items-center gap-1"><BadgeCheck className="size-5 text-sky-400" /> Verified artist</span> : 'Artist'}>
        <span>{formatNumber(a.monthly_plays)} plays this month · {plural(a.follower_count, 'follower')}</span>
      </CollectionHeader>
      <div className="flex items-center gap-6 px-4 py-4 md:px-6">
        <PlayFab onClick={controls.play} playing={controls.playing} label={`Play ${a.name}`} className="size-14" />
        <Button variant="outline" onClick={toggleFollow} aria-pressed={a.is_followed}>{a.is_followed ? 'Following' : 'Follow'}</Button>
      </div>
      <section className="px-2 md:px-4">
        <h2 className="mb-3 px-2 text-2xl font-bold">Popular</h2>
        {top.loading ? <TrackListSkeleton rows={5} /> : (
          <>
            <TrackList items={songs.slice(0, showAll ? 10 : 5).map((song) => ({ song }))} context={{ type: 'artist', id, name: a.name }} />
            {songs.length > 5 && <button onClick={() => setShowAll((s) => !s)} className="mt-2 px-3 text-sm font-bold text-muted hover:text-white">{showAll ? 'Show less' : 'See more'}</button>}
          </>
        )}
      </section>
      <section className="mt-10 px-4 md:px-6">
        <h2 className="mb-4 text-2xl font-bold">Discography</h2>
        {albums.loading ? <CardGridSkeleton /> : <CardGrid>{albums.data.map((al) => <AlbumCard key={al.id} album={al} />)}</CardGrid>}
      </section>
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
  const songs = useApi(() => catalogApi.songs({ genre: slug, page_size: 50 }), [slug])
  const albums = useApi(() => catalogApi.albums({ genre: slug, page_size: 12 }), [slug])
  const list = songs.data?.items || []
  const controls = usePlayContext('genre', slug, genre.data?.name, list)

  if (genre.error) return <ErrorState error={genre.error} onRetry={genre.reload} />
  return (
    <div>
      <div className="-mt-16 px-4 pb-8 pt-28 md:px-6" style={{ background: `linear-gradient(${genre.data?.color || '#333'}, transparent)` }}>
        <p className="text-sm font-semibold">Genre</p>
        <h1 className="text-5xl font-black md:text-7xl">{genre.data?.name || '…'}</h1>
      </div>
      <div className="flex items-center gap-6 px-4 pb-4 md:px-6">
        <PlayFab onClick={controls.play} playing={controls.playing} label="Play genre" className="size-14" />
      </div>
      <section className="px-2 md:px-4">
        <h2 className="mb-3 px-2 text-2xl font-bold">Popular {genre.data?.name} tracks</h2>
        {songs.loading ? <TrackListSkeleton /> : <TrackList items={list.map((song) => ({ song }))} context={{ type: 'genre', id: slug, name: genre.data?.name }} />}
      </section>
      <section className="mt-10 px-4 md:px-6">
        <h2 className="mb-4 text-2xl font-bold">Albums</h2>
        {albums.loading ? <CardGridSkeleton /> : <CardGrid>{albums.data.items.map((a) => <AlbumCard key={a.id} album={a} />)}</CardGrid>}
      </section>
    </div>
  )
}
