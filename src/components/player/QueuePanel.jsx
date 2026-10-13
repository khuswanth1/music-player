import { X } from 'lucide-react'
import { usePlayer } from '../../context/PlayerContext'
import { formatDuration } from '../../lib/format'
import { Cover, Equalizer } from '../ui'
import { songCover } from '../../lib/tracks'

function Row({ song, onPlay, onRemove, active, playing }) {
  return (
    <div className="group flex items-center gap-3 rounded-md p-2 hover:bg-hover">
      <button onClick={onPlay} className="flex min-w-0 flex-1 items-center gap-3 text-left" aria-label={`Play ${song.title}`}>
        <Cover src={songCover(song)} seed={song.album?.id || song.id} alt="" className="size-10 shrink-0" rounded="rounded" />
        <div className="min-w-0">
          <p className={`flex items-center gap-2 truncate text-sm font-semibold ${active ? 'text-accent' : ''}`}>
            {active && playing && <Equalizer />}<span className="truncate">{song.title}</span>
          </p>
          <p className="truncate text-xs text-muted">{song.artist.name}</p>
        </div>
      </button>
      <span className="text-xs tabular-nums text-muted">{formatDuration(song.duration_ms)}</span>
      {onRemove && (
        <button onClick={onRemove} aria-label={`Remove ${song.title} from queue`} className="text-muted opacity-0 hover:text-white group-hover:opacity-100 focus:opacity-100">
          <X className="size-4" />
        </button>
      )}
    </div>
  )
}

export default function QueuePanel({ onClose }) {
  const p = usePlayer()
  const upcoming = p.queue.slice(p.index + 1)
  return (
    <aside aria-label="Queue" className="hidden w-80 shrink-0 flex-col rounded-lg bg-surface lg:flex">
      <div className="flex items-center justify-between px-4 py-4">
        <h2 className="text-lg font-bold">Queue</h2>
        <button onClick={onClose} aria-label="Close queue" className="rounded-full p-1 text-muted hover:bg-hover hover:text-white"><X className="size-5" /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {p.session && <p className="px-2 pb-3 text-xs text-muted">In a group session, songs you add go to the shared queue on the session page.</p>}
        <h3 className="px-2 pb-1 text-sm font-bold text-muted">Now playing</h3>
        {p.current ? <Row song={p.current} active playing={p.isPlaying} onPlay={p.toggle} /> : <p className="px-2 text-sm text-subtle">Nothing playing</p>}
        <h3 className="mt-4 px-2 pb-1 text-sm font-bold text-muted">
          Next {p.context?.name ? <>from <span className="text-white">{p.context.name}</span></> : 'up'}
        </h3>
        {upcoming.length === 0 && <p className="px-2 text-sm text-subtle">Your queue is empty.</p>}
        {upcoming.map((song, i) => (
          <Row key={`${song.id}-${i}`} song={song} onPlay={() => p.jumpTo(p.index + 1 + i)}
            onRemove={() => p.removeFromQueue(p.index + 1 + i)} />
        ))}
      </div>
    </aside>
  )
}
