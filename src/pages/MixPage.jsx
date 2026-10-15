import { useParams } from 'react-router'
import { Pause, Play } from 'lucide-react'
import { mixApi } from '../api/endpoints'
import TrackList from '../components/TrackList'
import { Button, ErrorState, PageSkeleton } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useApi } from '../hooks/useApi'
import { isUnavailable } from '../lib/tracks'

export default function MixPage() {
  const { id } = useParams()
  const { data: mix, error, loading, reload } = useApi(() => mixApi.get(id), [id])
  const { playList, context, isPlaying, toggle } = usePlayer()
  if (loading) return <PageSkeleton />
  if (error) return <ErrorState error={error} onRetry={reload} />
  const songs = mix.songs.filter((s) => !isUnavailable(s))
  const ctx = { type: 'mix', id: mix.id, name: mix.title }
  const active = context?.type === 'mix' && context?.id === mix.id
  return (
    <div>
      <header className="px-4 pb-6 pt-10 md:px-6" style={{ backgroundImage: `linear-gradient(180deg, ${mix.color}, transparent)` }}>
        <p className="text-xs font-bold uppercase tracking-widest text-white/70">Made for you</p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-tight md:text-6xl">{mix.title}</h1>
        <p className="mt-2 text-white/80">{mix.subtitle} · {songs.length} songs</p>
        <Button variant="primary" className="mt-5 px-8 py-3" disabled={!songs.length}
          onClick={() => (active ? toggle() : playList(songs, 0, ctx))}>
          {active && isPlaying ? <><Pause className="size-4" fill="currentColor" /> Pause</> : <><Play className="size-4" fill="currentColor" /> Play</>}
        </Button>
      </header>
      <div className="px-4 md:px-6">
        <TrackList items={songs.map((song) => ({ song }))} context={ctx} />
      </div>
    </div>
  )
}
