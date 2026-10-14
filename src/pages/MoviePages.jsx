import { Link, useParams, useSearchParams } from 'react-router'
import { ExternalLink, Film, Pause, Play, SearchX } from 'lucide-react'
import { worldApi } from '../api/endpoints'
import { CardGrid, MediaCard } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import { AccessBadge } from '../components/TrackMeta'
import { CardGridSkeleton, EmptyState, ErrorState, PageSkeleton, inputClass, selectClass } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useApi, useDebounce } from '../hooks/useApi'
import { formatDuration } from '../lib/format'
import { languageName, useLanguages } from '../lib/languages'
import { CollectionHeader } from './CatalogPages'

const QUICK = ['Telugu movie songs', 'Hindi movie soundtracks', 'Tamil movie songs', 'Old Bollywood songs', 'Hollywood soundtracks', 'Korean movie soundtracks']

function SoundtrackCard({ item }) {
  const languages = useLanguages()
  return (
    <MediaCard to={`/soundtrack/${encodeURIComponent(item.id)}`} image={item.artwork_url} seed={item.id} title={item.movie_title}
      subtitle={[item.release_year, item.language ? languageName(languages, item.language) : 'Language unknown', item.credited_artist].filter(Boolean).join(' · ')} />
  )
}

export function MoviesPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const language = params.get('lang') || ''
  const country = params.get('country') || ''
  const decade = params.get('decade') || ''
  const languages = useLanguages()
  const debounced = useDebounce(q.trim(), 500)
  const set = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const year = decade ? { year_from: decade, year_to: Number(decade) + 9 } : {}
  const results = useApi((signal) => worldApi.movies({ q: debounced || undefined, language: language || undefined, country: country || undefined, ...year }, signal),
    [debounced, language, country, decade])
  const data = results.data

  return (
    <div className="px-4 md:px-6">
      <h1 className="mb-1 text-3xl font-extrabold tracking-tight">Movies &amp; Soundtracks</h1>
      <p className="mb-5 text-sm text-muted">Soundtrack albums from iTunes and MusicBrainz. Playback is only offered where a source supplies audio — otherwise a track shows as Preview or Unavailable.</p>
      <div className="mb-4 flex flex-wrap gap-2">
        <input type="search" value={q} onChange={(e) => set('q', e.target.value)} placeholder="Search a movie or try “Telugu movie songs”" aria-label="Search movies and soundtracks" className={`${inputClass} max-w-md flex-1`} />
        <select aria-label="Language" value={language} onChange={(e) => set('lang', e.target.value)} className={`${selectClass}`}>
          <option value="">Any language</option>
          {languages.filter((l) => l.featured).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
        <select aria-label="Release decade" value={decade} onChange={(e) => set('decade', e.target.value)} className={`${selectClass}`}>
          <option value="">Any year</option>
          {[2020, 2010, 2000, 1990, 1980, 1970, 1960].map((d) => <option key={d} value={d}>{d}s</option>)}
        </select>
        <input value={country} maxLength={2} onChange={(e) => set('country', e.target.value.toUpperCase())} placeholder="Country (IN)" aria-label="Release country code" className={`${inputClass} w-28`} />
      </div>
      <div className="mb-6 flex flex-wrap gap-2">
        {QUICK.map((s) => (
          <button key={s} onClick={() => setParams({ q: s }, { replace: true })} className="rounded-full bg-elevated px-3 py-1.5 text-sm font-semibold hover:bg-hover">{s}</button>
        ))}
      </div>
      {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
      {results.loading && <CardGridSkeleton />}
      {data && !results.loading && (
        <>
          <ProviderStatusList providers={data.providers} className="mb-4" />
          {Object.keys(data.interpreted).length > 0 && (
            <p className="mb-4 text-sm text-muted">Understood: {Object.entries(data.interpreted).map(([k, v]) => `${k.replace('_', ' ')} ${v}`).join(' · ')}</p>
          )}
          {data.items.length === 0
            ? <EmptyState icon={SearchX} title="No soundtracks found">Language and country filters only match what a source states for the release, so some albums are left out rather than mislabelled.</EmptyState>
            : (
              <CardGrid>
                {data.items.map((m) => <SoundtrackCard key={m.title + m.release_year} item={{ ...m.soundtracks[0], movie_title: m.title }} />)}
              </CardGrid>
            )}
        </>
      )}
    </div>
  )
}

export function SoundtrackPage() {
  const { id } = useParams()
  const languages = useLanguages()
  const { playList, current, isPlaying, toggle } = usePlayer()
  const { data, loading, error, reload } = useApi(() => worldApi.soundtrack(id), [id])
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading) return <PageSkeleton />

  const playable = data.tracks.filter((t) => t.song && t.song.playable)
  const playAt = (track) => {
    const songs = playable.map((t) => t.song)
    const i = songs.findIndex((s) => s.id === track.song.id)
    if (current?.id === track.song.id) return toggle()
    playList(songs, Math.max(0, i), { type: 'soundtrack', id: data.id, name: data.album_title })
  }
  const facts = [
    ['Soundtrack album', data.album_title], ['Release year', data.release_year], ['Language', data.language ? languageName(languages, data.language) : 'Unknown'],
    ['Country', data.country || 'Unknown'], ['Credited artist (usually the composer)', data.credited_artist || 'Unknown'], ['Genre', data.genre],
  ].filter(([, v]) => v)

  return (
    <div>
      <CollectionHeader image={data.artwork_url} seed={data.id} kicker="Movie soundtrack" title={data.movie_title} color="from-rose-800">
        <span className="font-bold">{data.credited_artist || 'Unknown artist'}</span>
        <span>{data.release_year ? `· ${data.release_year} ` : ''}· {data.tracks.length} tracks</span>
        <AccessBadge song={{ access: data.access }} className="ml-2" />
      </CollectionHeader>
      <div className="px-4 py-4 md:px-6">
        <dl className="mb-6 grid max-w-3xl grid-cols-1 gap-x-8 text-sm sm:grid-cols-2">
          {facts.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[11rem_1fr] gap-3 border-b border-line py-2"><dt className="text-muted">{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
        <p className="mb-4 text-xs text-subtle">
          The “credited artist” is the album&apos;s lead artist as listed by {data.provider === 'itunes' ? 'iTunes' : 'MusicBrainz'}; for film scores that is usually the composer, but the source doesn&apos;t say so explicitly.
          Singers are the artists credited on each track.
        </p>
        <h2 className="mb-2 text-xl font-bold">Track listing</h2>
        <ol className="divide-y divide-line rounded-lg ring-1 ring-line">
          {data.tracks.map((t, i) => {
            const active = t.song && current?.id === t.song.id
            const playableNow = Boolean(t.song?.playable)
            return (
              <li key={`${t.number}-${i}`} className="flex items-center gap-3 px-3 py-2">
                <span className="w-6 text-center text-muted">{t.number}</span>
                <button onClick={() => playAt(t)} disabled={!playableNow} aria-label={`${active && isPlaying ? 'Pause' : 'Play'} ${t.title}`}
                  className="rounded-full bg-white p-2 text-black hover:scale-105 disabled:bg-zinc-700 disabled:text-zinc-400">
                  {active && isPlaying ? <Pause className="size-3.5" fill="currentColor" /> : <Play className="size-3.5" fill="currentColor" />}
                </button>
                <div className="min-w-0 flex-1">
                  <p className={`truncate font-medium ${active ? 'text-accent' : ''}`}>{t.title}</p>
                  <p className="truncate text-xs text-muted">{t.singers || 'Singer not listed'}</p>
                </div>
                {t.song ? <AccessBadge song={t.song} /> : <AccessBadge song={{ access: 'metadata' }} />}
                {!playableNow && <span className="hidden text-xs text-amber-300 sm:block">Unavailable</span>}
                {t.duration_ms > 0 && <span className="w-12 text-right tabular-nums text-muted">{formatDuration(t.duration_ms)}</span>}
              </li>
            )
          })}
        </ol>
        {data.source_url && (
          <a href={data.source_url} target="_blank" rel="noopener noreferrer" className="mt-4 inline-flex items-center gap-1 text-sm text-muted hover:text-white">
            <ExternalLink className="size-4" /> View at {data.provider === 'itunes' ? 'Apple Music' : 'MusicBrainz'}
          </a>
        )}
        <p className="mt-6"><Link to="/movies" className="inline-flex items-center gap-1 text-sm text-muted hover:text-white"><Film className="size-4" /> More soundtracks</Link></p>
      </div>
    </div>
  )
}

