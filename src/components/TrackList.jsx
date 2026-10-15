import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { ArrowDown, ArrowUp, Clock3, Crown, Disc3, Download, ExternalLink, FolderLock, Heart, Info, ListPlus, MoreHorizontal, Pause, Play, Plus, Trash2, User2 } from 'lucide-react'
import { musicApi, privateAlbumApi } from '../api/endpoints'
import { useLibrary } from '../context/LibraryContext'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { formatDuration, timeAgo } from '../lib/format'
import { isUnavailable, songCover } from '../lib/tracks'
import { AccessBadge, CreditsModal, LanguageTag, LicenseBadge, RestrictionNote } from './TrackMeta'
import { Cover, Equalizer } from './ui'

export function LikeButton({ song, className = '', hoverOnly = false }) {
  const { isLiked, toggleLike } = useLibrary()
  const liked = isLiked(song)
  return (
    <button onClick={(e) => { e.stopPropagation(); toggleLike(song) }} aria-pressed={liked}
      aria-label={liked ? `Remove ${song.title} from Liked Songs` : `Save ${song.title} to Liked Songs`}
      className={`transition hover:scale-110 ${liked ? 'text-accent' : 'text-muted hover:text-white'} ${hoverOnly && !liked ? 'opacity-0 focus:opacity-100 group-hover:opacity-100' : ''} ${className}`}>
      <Heart className="size-4" fill={liked ? 'currentColor' : 'none'} />
    </button>
  )
}

const onlyEpisode = (song) => song?.kind === 'episode'

export function TrackMenu({ song, onRemove, onMoveUp, onMoveDown }) {
  const [open, setOpen] = useState(false)
  const [showPlaylists, setShowPlaylists] = useState(false)
  const [showAlbums, setShowAlbums] = useState(null) // null = closed, else the user's private albums
  const [credits, setCredits] = useState(false)
  const ref = useRef(null)
  const { addToQueue } = usePlayer()
  const { playlists, addToPlaylist } = useLibrary()
  const toast = useToast()
  const external = song.source && song.source !== 'local'

  const download = async () => {
    setOpen(false)
    try {
      const res = await musicApi.download(song.id)
      window.open(res.url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      toast.apiError(err)
    }
  }

  const openAlbums = async () => {
    try {
      setShowAlbums(await privateAlbumApi.list())
    } catch (err) {
      toast.apiError(err)
    }
  }

  const addToAlbum = async (album) => {
    setOpen(false)
    setShowAlbums(null)
    try {
      await privateAlbumApi.addTracks(album.id, [song.id])
      toast.success(`Added to ${album.name}`)
    } catch (err) {
      toast.apiError(err)
    }
  }

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => !ref.current?.contains(e.target) && setOpen(false)
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  const item = 'flex w-full items-center gap-3 rounded px-3 py-2 text-left text-sm hover:bg-hover'
  return (
    <div className="relative" ref={ref}>
      <button onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); setShowPlaylists(false); setShowAlbums(null) }}
        aria-label={`More options for ${song.title}`} aria-haspopup="menu" aria-expanded={open}
        className="rounded p-1 text-muted hover:text-white">
        <MoreHorizontal className="size-5" />
      </button>
      {open && (
        <div role="menu" onClick={(e) => e.stopPropagation()}
          className="absolute right-0 top-8 z-30 w-60 rounded-md bg-elevated p-1 shadow-2xl ring-1 ring-line">
          {showAlbums ? (
            <div className="max-h-64 overflow-y-auto">
              <p className="px-3 py-2 text-xs font-bold uppercase text-subtle">Add to private album</p>
              {showAlbums.length === 0 && <p className="px-3 py-2 text-sm text-muted">You have no private albums yet. <Link to="/private-albums" className="underline">Create one</Link>.</p>}
              {showAlbums.map((a) => (
                <button key={a.id} role="menuitem" className={item} onClick={() => addToAlbum(a)}>
                  <span className="truncate">{a.name}</span>
                </button>
              ))}
            </div>
          ) : !showPlaylists ? (
            <>
              <button role="menuitem" className={item} onClick={() => { addToQueue(song); setOpen(false) }}>
                <ListPlus className="size-4" /> Add to queue
              </button>
              <button role="menuitem" className={item} onClick={() => setShowPlaylists(true)}>
                <Plus className="size-4" /> Add to playlist
              </button>
              <button role="menuitem" className={item} onClick={openAlbums}>
                <FolderLock className="size-4" /> Add to private album
              </button>
              <Link role="menuitem" to={`/artist/${song.artist.id}`} className={item}><User2 className="size-4" /> Go to artist</Link>
              {song.album && <Link role="menuitem" to={`/album/${song.album.id}`} className={item}><Disc3 className="size-4" /> Go to album</Link>}
              <button role="menuitem" className={item} onClick={() => { setCredits(true); setOpen(false) }}>
                <Info className="size-4" /> Credits &amp; license
              </button>
              {external && song.download_allowed && (
                <button role="menuitem" className={item} onClick={download}><Download className="size-4" /> Download (from {song.source_name})</button>
              )}
              {song.access !== 'full' && !onlyEpisode(song) && (
                <a role="menuitem" href={`https://open.spotify.com/search/${encodeURIComponent(`${song.title} ${song.artist.name}`)}`}
                  target="_blank" rel="noopener noreferrer" className={item}>
                  <ExternalLink className="size-4" /> Find the full song on Spotify
                </a>
              )}
              {external && song.source_url && (
                <a role="menuitem" href={song.source_url} target="_blank" rel="noopener noreferrer" className={item}>
                  <ExternalLink className="size-4" /> Open on {song.source_name}
                </a>
              )}
              {/* Keyboard- and touch-friendly alternative to drag-and-drop */}
              {onMoveUp && <button role="menuitem" className={item} onClick={() => { onMoveUp(); setOpen(false) }}><ArrowUp className="size-4" /> Move up</button>}
              {onMoveDown && <button role="menuitem" className={item} onClick={() => { onMoveDown(); setOpen(false) }}><ArrowDown className="size-4" /> Move down</button>}
              {onRemove && (
                <button role="menuitem" className={`${item} text-danger`} onClick={() => { onRemove(); setOpen(false) }}>
                  <Trash2 className="size-4" /> Remove from this list
                </button>
              )}
            </>
          ) : (
            <div className="max-h-64 overflow-y-auto">
              <p className="px-3 py-2 text-xs font-bold uppercase text-subtle">Add to playlist</p>
              {playlists.length === 0 && <p className="px-3 py-2 text-sm text-muted">You have no playlists yet.</p>}
              {playlists.map((p) => (
                <button key={p.id} role="menuitem" className={item}
                  onClick={() => { addToPlaylist(p, [song]); setOpen(false) }}>
                  <span className="truncate">{p.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {credits && (
        // The dialog lives inside a draggable, double-clickable row: keep its events from reaching the row.
        <div onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}
          onDragStart={(e) => { e.preventDefault(); e.stopPropagation() }} draggable={false}>
          <CreditsModal song={song} open={credits} onClose={() => setCredits(false)} />
        </div>
      )}
    </div>
  )
}

/**
 * items: [{ key, song, addedAt?, addedBy?, onRemove? }]
 * onReorder(from, to) enables drag-and-drop reordering.
 */
export default function TrackList({ items, context, showAlbum = true, showCover = true, showAdded = false, onReorder, numbered = true }) {
  const { current, isPlaying, playList, toggle, prefetch } = usePlayer()
  const [dragFrom, setDragFrom] = useState(null)
  const [dragOver, setDragOver] = useState(null)
  const dragFromRef = useRef(null) // read by drop; state alone can be stale if events arrive before a re-render
  const songs = items.map((i) => i.song)

  const playAt = (index) => {
    if (current?.id === songs[index].id) return toggle()
    playList(songs, index, context)
  }

  return (
    <div role="table" aria-label="Tracks" className="text-sm">
      <div role="row" className="mb-2 grid grid-cols-[2rem_1fr_auto] items-center gap-4 border-b border-line px-3 pb-2 text-xs uppercase tracking-wider text-subtle md:grid-cols-[2rem_minmax(0,4fr)_minmax(0,3fr)_minmax(0,2fr)_6rem]">
        <span role="columnheader" className="text-center">#</span>
        <span role="columnheader">Title</span>
        <span role="columnheader" className="hidden md:block">{showAlbum ? 'Album' : ''}</span>
        <span role="columnheader" className="hidden md:block">{showAdded ? 'Date added' : ''}</span>
        <span role="columnheader" className="flex justify-end pr-8"><Clock3 className="size-4" aria-label="Duration" /></span>
      </div>
      {items.map((item, index) => {
        const { song } = item
        const active = current?.id === song.id
        const unavailable = isUnavailable(song)
        return (
          <div key={item.key ?? `${song.id}-${index}`} role="row"
            draggable={Boolean(onReorder)}
            onDragStart={(e) => { dragFromRef.current = index; setDragFrom(index); e.dataTransfer.effectAllowed = 'move' }}
            onDragOver={(e) => { if (onReorder) { e.preventDefault(); setDragOver(index) } }}
            onDragEnd={() => { dragFromRef.current = null; setDragFrom(null); setDragOver(null) }}
            onDrop={(e) => {
              e.preventDefault()
              const from = dragFromRef.current
              if (onReorder && from != null && from !== index) onReorder(from, index)
              dragFromRef.current = null
              setDragFrom(null)
              setDragOver(null)
            }}
            onPointerEnter={() => prefetch?.(song)}
            onDoubleClick={() => !unavailable && playAt(index)}
            title={unavailable ? song.restriction_reason || undefined : undefined}
            className={`group grid grid-cols-[2rem_1fr_auto] items-center gap-4 rounded-md px-3 py-1.5 hover:bg-white/10 md:grid-cols-[2rem_minmax(0,4fr)_minmax(0,3fr)_minmax(0,2fr)_6rem]
              ${dragOver === index && dragFrom !== index ? 'ring-1 ring-accent' : ''} ${unavailable ? 'opacity-60' : ''}`}>
            <div role="cell" className="flex justify-center text-muted">
              <span className={`group-hover:hidden ${active ? 'text-accent' : ''}`}>
                {active && isPlaying ? <Equalizer /> : numbered ? (song.track_number && !onReorder && context?.type === 'album' ? song.track_number : index + 1) : ''}
              </span>
              <button className="hidden text-white group-hover:block" disabled={unavailable}
                onClick={() => playAt(index)} aria-label={active && isPlaying ? `Pause ${song.title}` : `Play ${song.title}`}>
                {active && isPlaying ? <Pause className="size-4" fill="currentColor" /> : <Play className="size-4" fill="currentColor" />}
              </button>
            </div>
            <div role="cell" className="flex min-w-0 items-center gap-3">
              {showCover && <Cover src={songCover(song)} seed={song.album?.id || song.id} alt="" className="size-10 shrink-0" rounded="rounded" />}
              <div className="min-w-0">
                <div className={`flex items-center gap-1.5 truncate font-medium ${active ? 'text-accent' : 'text-white'}`}>
                  <span className="truncate">{song.title}</span>
                  {song.is_premium && <Crown className="size-3.5 shrink-0 text-amber-300" aria-label="Premium" />}
                  {song.explicit && <span className="rounded-sm bg-zinc-400 px-1 text-[10px] font-bold text-black">E</span>}
                  <LanguageTag code={song.language} className="hidden sm:inline" />
                  <AccessBadge song={song} />
                  {song.source && song.source !== 'local' && <LicenseBadge song={song} className="hidden lg:inline" />}
                </div>
                <div className="flex min-w-0 items-center gap-2">
                  <Link to={`/artist/${song.artist.id}`} className="truncate text-muted hover:text-white hover:underline" onClick={(e) => e.stopPropagation()}>
                    {song.artist.name}
                  </Link>
                  {song.source && song.source !== 'local' && !unavailable && <span className="hidden shrink-0 text-xs text-subtle sm:inline">· {song.source_name}</span>}
                  <RestrictionNote song={song} />
                </div>
              </div>
            </div>
            <div role="cell" className="hidden truncate text-muted md:block">
              {showAlbum && song.album && <Link to={`/album/${song.album.id}`} className="hover:text-white hover:underline">{song.album.title}</Link>}
            </div>
            <div role="cell" className="hidden truncate text-muted md:block">
              {showAdded && item.addedAt && <span title={item.addedBy ? `Added by ${item.addedBy.display_name}` : undefined}>{timeAgo(item.addedAt)}{item.addedBy ? ` · ${item.addedBy.display_name}` : ''}</span>}
            </div>
            <div role="cell" className="flex items-center justify-end gap-3">
              <LikeButton song={song} hoverOnly />
              <span className="w-10 text-right tabular-nums text-muted">{formatDuration(song.duration_ms)}</span>
              <TrackMenu song={song} onRemove={item.onRemove}
                onMoveUp={onReorder && index > 0 ? () => onReorder(index, index - 1) : undefined}
                onMoveDown={onReorder && index < items.length - 1 ? () => onReorder(index, index + 1) : undefined} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
