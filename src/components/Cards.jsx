import { Link } from 'react-router'
import { Pause, Play } from 'lucide-react'
import { catalogApi, playlistApi } from '../api/endpoints'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { Cover } from './ui'

export function PlayFab({ onClick, playing, label, className = '' }) {
  return (
    <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick() }} aria-label={label}
      className={`flex size-12 items-center justify-center rounded-full bg-accent text-black shadow-xl transition hover:scale-105 hover:bg-accent-strong ${className}`}>
      {playing ? <Pause className="size-5" fill="currentColor" /> : <Play className="ml-0.5 size-5" fill="currentColor" />}
    </button>
  )
}

/** Play an album/playlist straight from its card; the tracks are fetched on demand. */
function useCollectionPlayback(kind, id, name) {
  const { playList, context, isPlaying, toggle } = usePlayer()
  const toast = useToast()
  const active = context?.type === kind && context?.id === id
  const play = async () => {
    if (active) return toggle()
    try {
      const data = kind === 'album' ? await catalogApi.album(id) : await playlistApi.get(id)
      const songs = kind === 'album' ? data.songs : data.tracks.map((t) => t.song)
      if (!songs.length) return toast.info('Nothing to play yet')
      playList(songs, 0, { type: kind, id, name })
    } catch (err) {
      toast.apiError(err)
    }
  }
  return { play, playing: active && isPlaying }
}

export function MediaCard({ to, image, seed, title, subtitle, round = false, kind, id }) {
  const playback = useCollectionPlayback(kind, id, title)
  return (
    <Link to={to} className="group relative block rounded-lg bg-surface p-3 transition hover:bg-elevated">
      <div className="relative">
        <Cover src={image} seed={seed || id} alt={title} rounded={round ? 'rounded-full' : 'rounded-md'} className="w-full shadow-lg" />
        {kind && (
          <PlayFab onClick={playback.play} playing={playback.playing} label={`Play ${title}`}
            className={`absolute bottom-2 right-2 translate-y-2 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 focus:translate-y-0 focus:opacity-100 ${playback.playing ? 'translate-y-0 opacity-100' : ''}`} />
        )}
      </div>
      <h3 className="mt-3 truncate font-bold">{title}</h3>
      {subtitle && <p className="mt-1 line-clamp-2 text-sm text-muted">{subtitle}</p>}
    </Link>
  )
}

export function AlbumCard({ album }) {
  return <MediaCard to={`/album/${album.id}`} image={album.cover_url} title={album.title} kind="album" id={album.id}
    subtitle={album.release_date ? `${new Date(album.release_date).getFullYear()} · ${album.artist.name}` : album.artist.name} />
}

export function ArtistCard({ artist }) {
  return <MediaCard to={`/artist/${artist.id}`} image={artist.image_url} title={artist.name} subtitle="Artist" round id={artist.id} />
}

export function PlaylistCard({ playlist }) {
  return <MediaCard to={`/playlist/${playlist.id}`} image={playlist.cover_url} title={playlist.name} kind="playlist" id={playlist.id}
    subtitle={playlist.description || `By ${playlist.owner.display_name}`} />
}

export function CardGrid({ children }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">{children}</div>
}

/** Horizontally scrolling row on small screens, grid on large ones. */
export function CardRow({ children }) {
  return (
    <div className="-mx-2 flex gap-3 overflow-x-auto px-2 pb-2 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 [&>*]:w-40 [&>*]:shrink-0 sm:[&>*]:w-auto">
      {children}
    </div>
  )
}
