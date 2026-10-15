import { Link } from 'react-router'
import { Music2 } from 'lucide-react'
import { mixApi } from '../api/endpoints'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { isUnavailable, songCover } from '../lib/tracks'
import { PlayFab } from './Cards'

/** A playlist made for one person: their colour, a collage of the first songs, and a play button. */
export function MixCard({ mix }) {
  const { playList, context, isPlaying, toggle } = usePlayer()
  const toast = useToast()
  const active = context?.type === 'mix' && context?.id === mix.id
  const covers = mix.preview.map(songCover).filter(Boolean).slice(0, 4)

  const play = async () => {
    if (active) return toggle()
    try {
      const full = await mixApi.get(mix.id)
      playList(full.songs.filter((s) => !isUnavailable(s)), 0, { type: 'mix', id: mix.id, name: mix.title })
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <Link to={`/mix/${encodeURIComponent(mix.id)}`}
      className="group relative block overflow-hidden rounded-lg p-3 transition hover:brightness-110"
      style={{ backgroundImage: `linear-gradient(160deg, ${mix.color}, #121212 130%)` }}>
      <div className="relative grid aspect-square w-full grid-cols-2 gap-0.5 overflow-hidden rounded-md shadow-lg">
        {covers.length >= 4 ? covers.map((src, i) => <img key={i} src={src} alt="" loading="lazy" className="size-full object-cover" />)
          : covers.length ? <img src={covers[0]} alt="" loading="lazy" className="col-span-2 row-span-2 size-full object-cover" />
            : <div className="col-span-2 row-span-2 flex items-center justify-center bg-black/30"><Music2 className="size-1/3 text-white/70" /></div>}
        <PlayFab onClick={play} playing={active && isPlaying} label={`Play ${mix.title}`}
          className={`absolute bottom-2 right-2 translate-y-2 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 focus:translate-y-0 focus:opacity-100 ${active && isPlaying ? 'translate-y-0 opacity-100' : ''}`} />
      </div>
      <h3 className="mt-3 truncate font-bold text-white">{mix.title}</h3>
      <p className="mt-1 line-clamp-2 text-sm text-white/70">{mix.subtitle}</p>
    </Link>
  )
}
