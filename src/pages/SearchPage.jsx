import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ExternalLink, Globe2, SearchX } from 'lucide-react'
import { catalogApi, musicApi, searchApi, worldApi } from '../api/endpoints'
import { AlbumCard, CardGrid, MediaCard, PlaylistCard } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import TrackList from '../components/TrackList'
import { Button, CardGridSkeleton, EmptyState, ErrorState, Spinner, TrackListSkeleton, selectClass } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useApi, useDebounce } from '../hooks/useApi'
import { formatDuration, plural } from '../lib/format'
import { languageName, useLanguages } from '../lib/languages'
import { ArtistResultCard } from './ArtistsPage'
import { EpisodeRow, PodcastCard } from './PodcastPages'

const TABS = [
  ['all', 'All'], ['songs', 'Songs'], ['artists', 'Artists'], ['albums', 'Albums'], ['soundtracks', 'Soundtracks'],
  ['podcasts', 'Podcasts'], ['episodes', 'Episodes'], ['playlists', 'Playlists'], ['private_albums', 'Private albums'],
]
const ALL_CATEGORIES = 'songs,artists,albums,soundtracks,podcasts,episodes,playlists,private_albums,facets'
const PAGE_SIZE = 20
const THIS_YEAR = new Date().getFullYear()

/** A genre tile. Genres with no tracks yet are still offered: opening one asks the music sources for it first. */
function GenreTile({ g }) {
  const navigate = useNavigate()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const empty = g.id === null
  const open = async (e) => {
    if (!empty) return
    e.preventDefault()
    setBusy(true)
    try {
      const res = await worldApi.fetchGenre(g.slug)
      if (res.imported + res.updated === 0) toast.info(`The sources have no ${g.name} tracks we can play right now`)
      else navigate(`/genre/${res.slug}`)
    } catch (err) {
      toast.apiError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Link to={`/genre/${g.slug}`} onClick={open} style={{ backgroundColor: g.color }} aria-busy={busy}
      className={`relative h-32 overflow-hidden rounded-lg p-4 text-2xl font-extrabold text-black/85 transition hover:scale-[1.02] ${empty ? 'opacity-80' : ''}`}>
      {g.name}
      {empty && <span className="absolute bottom-3 left-4 text-xs font-semibold">{busy ? 'Finding tracks…' : 'Tap to find tracks'}</span>}
    </Link>
  )
}

function GenreGrid() {
  const { data, loading } = useApi(() => worldApi.genres({ include_empty: true }), [])
  const languages = useLanguages().filter((l) => l.featured || l.playable_count > 0).slice(0, 18)
  return (
    <div className="px-4 md:px-6">
      {languages.length > 0 && (
        <section className="mb-8">
          <div className="mb-3 flex items-end justify-between">
            <h1 className="text-2xl font-bold">Browse by language</h1>
            <Link to="/languages" className="text-sm font-bold text-muted hover:underline">All languages</Link>
          </div>
          <div className="flex flex-wrap gap-2">
            {languages.map((l) => (
              <Link key={l.code} to={`/language/${l.code}`} className="rounded-full bg-elevated px-4 py-2 text-sm font-semibold hover:bg-hover">
                <span lang={l.code} dir={l.rtl ? 'rtl' : undefined}>{l.native_name}</span>
                {l.native_name !== l.name && <span className="ml-1.5 text-xs font-normal text-muted">{l.name}</span>}
              </Link>
            ))}
          </div>
        </section>
      )}
      <section className="mb-8">
        <h2 className="mb-3 text-2xl font-bold">Try searching</h2>
        <div className="flex flex-wrap gap-2">
          {['Telugu latest songs', 'Telugu old songs 1990', 'Hindi movie songs', 'English pop music', 'Korean singers', 'Japanese albums', 'Latest podcasts', 'Worldwide classical music'].map((s) => (
            <Link key={s} to={`/search?q=${encodeURIComponent(s)}`} className="rounded-full border border-line px-4 py-2 text-sm hover:border-white">{s}</Link>
          ))}
        </div>
      </section>
      <h2 className="mb-5 text-2xl font-bold">Browse all</h2>
      {loading ? <CardGridSkeleton /> : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {data?.map((g) => <GenreTile key={g.slug} g={g} />)}
        </div>
      )}
    </div>
  )
}

function Section({ title, count, children }) {
  return (
    <section>
      <h2 className="mb-3 text-2xl font-bold">{title} {count != null && <span className="text-base font-normal text-muted">({count})</span>}</h2>
      {children}
    </section>
  )
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const { user } = useAuth()
  const q = params.get('q') || ''
  const tab = params.get('type') || 'all'
  const filters = {
    language: params.get('lang') || '', country: params.get('country') || '', year: params.get('year') || '',
    genre: params.get('genre') || '', source: params.get('source') || '', full_only: params.get('full') === '1',
  }
  const debounced = useDebounce(q.trim(), 250) // provider searches cost quota: wait until typing settles
  const languages = useLanguages()
  const genres = useApi(() => catalogApi.genres(), [])
  const providers = useApi(() => musicApi.providers(), [])
  const countries = useApi(() => worldApi.countries(), [])
  const [more, setMore] = useState({ key: '', songs: [], page: 1, hasMore: null, loading: false })

  const set = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const key = JSON.stringify([debounced, tab, filters])
  const categories = tab === 'all' ? ALL_CATEGORIES : tab
  const request = (page, signal, live = true) => searchApi.global({
    live: live ? undefined : 'false',
    q: debounced, categories, language: filters.language || undefined, country: filters.country || undefined,
    year: filters.year || undefined, genre: filters.genre || undefined, source: filters.source || undefined,
    full_only: filters.full_only || undefined, page, limit: tab === 'all' ? 8 : PAGE_SIZE,
  }, signal)
  // Two passes: what the catalog already has appears at once, then the live provider results replace it.
  const local = useApi((signal) => (debounced.length >= 2 ? request(1, signal, false) : Promise.resolve(null)), [key])
  const live = useApi((signal) => (debounced.length >= 2 ? request(1, signal) : Promise.resolve(null)), [key])
  const results = {
    data: live.data || local.data,
    error: live.data || local.data ? null : live.error || local.error,
    loading: !live.data && !local.data && (live.loading || local.loading),
    reload: live.reload,
  }

  // Search history: remember a query once the user has paused on it.
  const settled = useDebounce(q.trim(), 1500)
  useEffect(() => {
    if (user && settled.length >= 2) searchApi.record(settled).catch(() => {})
  }, [settled, user])

  const data = results.data
  const extra = more.key === key ? more : { songs: [], page: 1, hasMore: null, loading: false }
  const loadMore = async () => {
    setMore({ ...extra, key, loading: true })
    try {
      const next = await request(extra.page + 1)
      setMore({ key, songs: [...extra.songs, ...next.songs], page: extra.page + 1, hasMore: next.has_more, loading: false })
    } catch {
      setMore({ ...extra, key, loading: false })
    }
  }
  const songs = useMemo(() => [...(data?.songs || []), ...extra.songs], [data, extra.songs])
  const hasMore = extra.hasMore ?? data?.has_more

  if (!q.trim()) return <GenreGrid />
  const loading = results.loading || debounced !== q.trim()
  const total = data ? ['songs', 'artists', 'albums', 'soundtracks', 'podcasts', 'episodes', 'playlists', 'private_albums', 'metadata_only', 'languages', 'countries', 'genres']
    .reduce((n, k) => n + (data[k]?.length || 0), 0) : 0
  const showTab = (t) => tab === 'all' || tab === t
  const facetChips = data && tab === 'all' ? [
    ...data.languages.map((l) => ({ key: `l-${l.code}`, to: `/language/${l.code}`, label: `${l.name} songs` })),
    ...data.genres.map((g) => ({ key: `g-${g.id}`, to: `/genre/${g.slug}`, label: `${g.name} genre` })),
    ...data.countries.map((c) => ({ key: `c-${c.code}`, to: `/search?q=${encodeURIComponent(q)}&country=${c.code}`, label: c.name })),
    ...data.years.slice(0, 10).map((y) => ({ key: `y-${y}`, to: `/search?q=${encodeURIComponent(q)}&year=${y}`, label: String(y) })),
  ] : []

  return (
    <div className="px-4 md:px-6">
      <h1 className="sr-only">Search results for {q}</h1>
      <div className="mb-4 flex flex-wrap items-center gap-2" role="tablist" aria-label="Result categories">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => set('type', id === 'all' ? '' : id)}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${tab === id ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>{label}</button>
        ))}
      </div>
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <select aria-label="Filter by language" value={filters.language} onChange={(e) => set('lang', e.target.value)} className={`${selectClass}`}>
          <option value="">Any language</option>
          {languages.filter((l) => l.featured || l.playable_count > 0).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
        <select aria-label="Filter by country" value={filters.country} onChange={(e) => set('country', e.target.value)} className={`${selectClass}`}>
          <option value="">Any country</option>
          {countries.data?.filter((c) => c.code).map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          {filters.country && !countries.data?.some((c) => c.code === filters.country) && <option value={filters.country}>{filters.country}</option>}
        </select>
        <select aria-label="Filter by release year" value={filters.year} onChange={(e) => set('year', e.target.value)} className={`${selectClass}`}>
          <option value="">Any year</option>
          {Array.from({ length: THIS_YEAR - 1949 }, (_, i) => THIS_YEAR - i).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select aria-label="Filter by genre" value={filters.genre} onChange={(e) => set('genre', e.target.value)} className={`${selectClass}`}>
          <option value="">All genres</option>
          {genres.data?.map((g) => <option key={g.id} value={g.slug}>{g.name}</option>)}
        </select>
        <select aria-label="Filter by source" value={filters.source} onChange={(e) => set('source', e.target.value)} className={`${selectClass}`}>
          <option value="">Any source</option>
          {providers.data?.filter((p) => p.enabled).map((p) => <option key={p.key} value={p.key}>{p.name}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={filters.full_only} onChange={(e) => set('full', e.target.checked ? '1' : '')} className="size-4 accent-emerald-500" /> Full songs only
        </label>
      </div>

      {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
      {loading && <div className="space-y-8" aria-busy="true"><TrackListSkeleton rows={4} /><CardGridSkeleton count={6} /></div>}
      {!loading && data && (
        <div className="space-y-10">
          {Object.keys(data.interpreted).length > 0 && (
            <p className="text-sm text-muted">
              Understood: {Object.entries(data.interpreted).filter(([k]) => k !== 'text').map(([k, v]) => `${k.replace('_', ' ')} ${k === 'language' ? languageName(languages, v) : v}`).join(' · ') || 'plain text'}
              {data.interpreted.text ? ` · searching “${data.interpreted.text}”` : ''}
            </p>
          )}
          <ProviderStatusList providers={data.providers} />
          {facetChips.length > 0 && (
            <div className="flex flex-wrap gap-2" aria-label="Related">
              {facetChips.map((c) => <Link key={c.key} to={c.to} className="rounded-full bg-elevated px-4 py-2 text-sm font-semibold hover:bg-hover">{c.label}</Link>)}
            </div>
          )}
          {total === 0 && (
            <EmptyState icon={SearchX} title={`Nothing found for “${q}”`}>
              Check the spelling, remove a filter, or try fewer keywords. Language and country filters only match what a source states, so tracks with missing metadata aren&apos;t included.
            </EmptyState>
          )}
          {showTab('songs') && songs.length > 0 && (
            <Section title="Songs">
              <TrackList items={songs.map((song) => ({ song }))} context={{ type: 'search', name: `Search: ${q}` }} />
              {hasMore && tab !== 'all' && <div className="mt-4 flex justify-center"><Button variant="outline" onClick={loadMore} loading={extra.loading}>Load more</Button></div>}
              {tab === 'all' && hasMore && <button onClick={() => set('type', 'songs')} className="mt-3 text-sm font-bold text-muted hover:text-white">See all songs</button>}
              {data.metadata_only.length > 0 && (
                <div className="mt-8">
                  <h3 className="text-lg font-bold">Metadata only</h3>
                  <p className="mb-3 text-sm text-muted">Known recordings (per MusicBrainz) with no authorized free audio source, so they can&apos;t be played here.</p>
                  <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
                    {data.metadata_only.map((r) => (
                      <li key={r.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-medium text-zinc-300">{r.title}</p>
                          <p className="truncate text-xs text-muted">{r.artist_name}{r.release_title ? ` · ${r.release_title}` : ''}{r.release_date ? ` · ${r.release_date.slice(0, 4)}` : ''}</p>
                        </div>
                        {r.duration_ms && <span className="tabular-nums text-muted">{formatDuration(r.duration_ms)}</span>}
                        <a href={r.url} target="_blank" rel="noopener noreferrer" aria-label={`${r.title} on MusicBrainz`} className="text-muted hover:text-white"><ExternalLink className="size-4" /></a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          )}
          {showTab('artists') && data.artists.length > 0 && <Section title="Artists &amp; singers"><CardGrid>{data.artists.map((a) => <ArtistResultCard key={a.id} artist={a} />)}</CardGrid></Section>}
          {showTab('albums') && data.albums.length > 0 && <Section title="Albums"><CardGrid>{data.albums.map((a) => <AlbumCard key={a.id} album={a} />)}</CardGrid></Section>}
          {showTab('soundtracks') && data.soundtracks.length > 0 && (
            <Section title="Movie soundtracks">
              <CardGrid>
                {data.soundtracks.map((s) => (
                  <MediaCard key={s.id} to={`/soundtrack/${encodeURIComponent(s.id)}`} image={s.artwork_url} seed={s.id} title={s.movie_title}
                    subtitle={[s.release_year, s.language ? languageName(languages, s.language) : 'Language unknown', s.credited_artist].filter(Boolean).join(' · ')} />
                ))}
              </CardGrid>
            </Section>
          )}
          {showTab('podcasts') && data.podcasts.length > 0 && <Section title="Podcasts"><CardGrid>{data.podcasts.map((p) => <PodcastCard key={p.id} podcast={p} />)}</CardGrid></Section>}
          {showTab('episodes') && data.episodes.length > 0 && (
            <Section title="Podcast episodes">
              <div className="space-y-1">{data.episodes.map((e) => <EpisodeRow key={e.id} episode={e} queue={data.episodes} showPodcast />)}</div>
            </Section>
          )}
          {showTab('playlists') && data.playlists.length > 0 && <Section title="Playlists"><CardGrid>{data.playlists.map((p) => <PlaylistCard key={p.id} playlist={p} />)}</CardGrid></Section>}
          {showTab('private_albums') && data.private_albums.length > 0 && (
            <Section title="Your private albums">
              <CardGrid>
                {data.private_albums.map((a) => (
                  <MediaCard key={a.id} to={`/private-albums/${a.id}`} image={a.cover_url} seed={a.id} title={a.name} subtitle={`${plural(a.track_count, 'track')} · Private`} />
                ))}
              </CardGrid>
            </Section>
          )}
        </div>
      )}
      {!loading && !data && q.trim().length === 1 && <p className="text-sm text-muted">Keep typing — at least two characters.</p>}
      {live.loading && <p className="mt-6 flex items-center gap-2 text-sm text-muted" role="status"><Globe2 className="size-4 text-accent" /> <Spinner className="size-4" /> Asking the sources for more…</p>}
    </div>
  )
}
