import { useState } from 'react'
import { Link } from 'react-router'
import { ListMusic, Pause, Play, Repeat, Repeat1, Shuffle, SkipBack, SkipForward, Users, Volume1, Volume2, VolumeX } from 'lucide-react'
import { usePlayer } from '../../context/PlayerContext'
import { formatDuration } from '../../lib/format'
import { LikeButton } from '../TrackList'
import { isEpisode, licenseShort, songCover } from '../../lib/tracks'
import { AccessBadge, CreditsModal } from '../TrackMeta'
import { Cover, Spinner } from '../ui'

function Slider({ value, max, onChange, onCommit, label, className = '', disabled = false }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0
  return (
    <input type="range" className={`slider w-full disabled:cursor-not-allowed disabled:opacity-50 ${className}`} min={0} max={max || 0}
      step="any" value={Math.min(value, max || 0)} disabled={disabled} aria-label={label} style={{ '--pct': `${pct}%` }}
      onChange={(e) => onChange(Number(e.target.value))}
      onPointerUp={(e) => onCommit?.(Number(e.target.value))}
      onKeyUp={(e) => onCommit?.(Number(e.target.value))} />
  )
}

export default function PlayerBar({ onToggleQueue, queueOpen }) {
  const p = usePlayer()
  const [scrub, setScrub] = useState(null)
  const [credits, setCredits] = useState(false)
  const song = p.current
  const episode = isEpisode(song)
  const external = song && !episode && song.source && song.source !== 'local'
  const shownPos = scrub ?? p.position
  const memberLocked = p.session && !p.session.isHost
  const VolumeIcon = p.muted || p.volume === 0 ? VolumeX : p.volume < 0.5 ? Volume1 : Volume2

  return (
    <footer aria-label="Now playing" className="border-t border-line bg-black px-3 py-2 md:px-4">
      {p.session && (
        <Link to="/sessions" className="mb-1 flex items-center justify-center gap-2 text-xs font-semibold text-accent">
          <Users className="size-3.5" /> Listening together · {p.session.name}{memberLocked ? ' · host controls playback' : ''}
        </Link>
      )}
      <div className="grid grid-cols-[1fr_auto] items-center gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 items-center gap-3">
          {song ? (
            <>
              <Cover src={songCover(song)} seed={song.album?.id || song.id} alt="" className="size-12 shrink-0 md:size-14" />
              <div className="min-w-0">
                {episode ? (
                  <>
                    <Link to={`/podcast/${encodeURIComponent(song.podcast_id)}`} className="block truncate text-sm font-semibold hover:underline">{song.title}</Link>
                    <span className="block truncate text-xs text-muted">{song.artist.name}</span>
                  </>
                ) : (
                  <>
                    <Link to={song.album ? `/album/${song.album.id}` : `/artist/${song.artist.id}`} className="block truncate text-sm font-semibold hover:underline">{song.title}</Link>
                    <Link to={`/artist/${song.artist.id}`} className="block truncate text-xs text-muted hover:text-white hover:underline">{song.artist.name}</Link>
                  </>
                )}
                <div className="flex items-center gap-1.5">
                  <AccessBadge song={song} />
                  {external && (
                    <button onClick={() => setCredits(true)} title={song.attribution || undefined}
                      className="block max-w-full truncate text-[11px] text-subtle hover:text-white">
                      {[song.license_code !== 'preview' && licenseShort(song), song.source_name].filter(Boolean).join(' · ')}
                    </button>
                  )}
                </div>
              </div>
              {!episode && <LikeButton song={song} className="ml-2 hidden sm:block" />}
            </>
          ) : (
            <p className="text-sm text-muted">Pick something to play</p>
          )}
        </div>

        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center gap-4 md:gap-5">
            <button onClick={p.toggleShuffle} disabled={Boolean(p.session)} aria-pressed={p.shuffle} aria-label="Shuffle (S)" title="Shuffle (S)"
              className={`hidden disabled:opacity-30 md:block ${p.shuffle ? 'text-accent' : 'text-muted hover:text-white'}`}><Shuffle className="size-4" /></button>
            <button onClick={p.prev} disabled={!song || memberLocked} aria-label="Previous (Shift+←)" title="Previous (Shift+←)" className="text-muted hover:text-white disabled:opacity-30"><SkipBack className="size-5" fill="currentColor" /></button>
            <button onClick={p.toggle} disabled={!song || memberLocked} aria-label={p.isPlaying ? 'Pause (Space)' : 'Play (Space)'}
              className="flex size-9 items-center justify-center rounded-full bg-white text-black transition hover:scale-105 disabled:opacity-40">
              {p.buffering ? <Spinner className="size-4" /> : p.isPlaying ? <Pause className="size-4" fill="currentColor" /> : <Play className="ml-0.5 size-4" fill="currentColor" />}
            </button>
            <button onClick={p.next} disabled={!song || memberLocked} aria-label="Next (Shift+→)" title="Next (Shift+→)" className="text-muted hover:text-white disabled:opacity-30"><SkipForward className="size-5" fill="currentColor" /></button>
            <button onClick={p.cycleRepeat} disabled={Boolean(p.session)} aria-label={`Repeat: ${p.repeat} (R)`} title={`Repeat: ${p.repeat} (R)`}
              className={`hidden disabled:opacity-30 md:block ${p.repeat !== 'off' ? 'text-accent' : 'text-muted hover:text-white'}`}>
              {p.repeat === 'one' ? <Repeat1 className="size-4" /> : <Repeat className="size-4" />}
            </button>
          </div>
          <div className="hidden w-full max-w-xl items-center gap-2 text-[11px] tabular-nums text-muted md:flex">
            <span className="w-10 text-right">{formatDuration(shownPos)}</span>
            <Slider value={shownPos} max={p.duration} label="Seek" disabled={!song || memberLocked}
              onChange={setScrub} onCommit={(v) => { p.seek(v); setScrub(null) }} />
            <span className="w-10">{formatDuration(p.duration)}</span>
          </div>
        </div>

        <div className="hidden items-center justify-end gap-3 md:flex">
          <button onClick={onToggleQueue} aria-pressed={queueOpen} aria-label="Queue (Q)" title="Queue (Q)"
            className={queueOpen ? 'text-accent' : 'text-muted hover:text-white'}><ListMusic className="size-5" /></button>
          <button onClick={p.toggleMute} aria-label={p.muted ? 'Unmute (M)' : 'Mute (M)'} title="Mute (M)" className="text-muted hover:text-white"><VolumeIcon className="size-5" /></button>
          <Slider value={p.muted ? 0 : p.volume} max={1} onChange={p.setVolume} label="Volume" className="max-w-28" />
        </div>
      </div>
      {!episode && <CreditsModal song={song} open={credits} onClose={() => setCredits(false)} />}
      {/* Thin progress line for mobile */}
      <div className="mt-2 h-0.5 w-full rounded bg-zinc-700 md:hidden">
        <div className="h-full rounded bg-white" style={{ width: `${p.duration ? (p.position / p.duration) * 100 : 0}%` }} />
      </div>
    </footer>
  )
}
