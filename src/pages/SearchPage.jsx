import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ExternalLink, Globe2, SearchX } from 'lucide-react'
import { catalogApi, musicApi } from '../api/endpoints'
import { AlbumCard, ArtistCard, CardGrid, PlaylistCard } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import TrackList from '../components/TrackList'
import { CardGridSkeleton, EmptyState, ErrorState, Spinner, TrackListSkeleton, inputClass } from '../components/ui'
import { useApi, useDebounce } from '../hooks/useApi'
import { formatDuration } from '../lib/format'
import { useLanguages } from '../lib/languages'

const TABS = [
  { id: 'all', label: 'All' }, { id: 'song', label: 'Songs' }, { id: 'artist', label: 'Artists' },
  { id: 'album', label: 'Albums' }, { id: 'playlist', label: 'Playlists' },
]

function Pager({ page, pages, onChange }) {
  if (pages <= 1) return null
  return (
    <div className="mt-6 flex items-center justify-center gap-3 text-sm">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)} className="rounded-full border border-line px-4 py-1.5 disabled:opacity-40">Previous</button>
      <span className="text-muted">Page {page} of {pages}</span>
      <button disabled={page >= pages} onClick={() => onChange(page + 1)} className="rounded-full border border-line px-4 py-1.5 disabled:opacity-40">Next</button>
    </div>
  )
}

function GenreGrid() {
  const { data, loading } = useApi(() => catalogApi.genres(), [])
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
      <h1 className="mb-5 text-2xl font-bold">Browse all</h1>
      {loading ? <CardGridSkeleton /> : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {data?.map((g) => (
            <Link key={g.id} to={`/genre/${g.slug}`} style={{ backgroundColor: g.color }}
              className="h-32 rounded-lg p-4 text-2xl font-extrabold text-black/85 transition hover:scale-[1.02]">{g.name}</Link>
          ))}
        </div>
      )}
    </div>
  )
}

/** Live results from every enabled provider; slower than the local catalog, so it loads separately. */
function OpenCatalogResults({ q, language, localIds }) {
  const results = useApi((signal) => (q.length >= 2
    ? musicApi.globalSearch({ q, language: language || undefined, limit: 20 }, signal) : Promise.resolve(null)), [q, language])
  const data = results.data
  const fresh = (data?.songs || []).filter((song) => !localIds.has(song.id))

  return (
    <section aria-busy={results.loading}>
      <h2 className="mb-1 flex items-center gap-2 text-2xl font-bold"><Globe2 className="size-6 text-accent" /> From open catalogs</h2>
      <p className="mb-3 text-sm text-muted">Searched live; only tracks their source lets us stream are playable. <Link to="/sources" className="underline hover:text-white">Sources</Link></p>
      {results.loading && <p className="flex items-center gap-2 py-4 text-sm text-muted"><Spinner className="size-4" /> Asking the sources…</p>}
      {results.error && <ErrorState error={results.error} onRetry={results.reload} title="Couldn't reach the sources" />}
      {data && !results.loading && (
        <>
          <ProviderStatusList providers={data.providers} className="mb-4" />
          {fresh.length > 0
            ? <TrackList items={fresh.map((song) => ({ song }))} context={{ type: 'search', name: `Search: ${q}` }} />
            : <p className="py-2 text-sm text-muted">No additional tracks from the open catalogs{language ? ' in this language' : ''}.</p>}
          {data.metadata_only.length > 0 && (
            <div className="mt-8">
              <h3 className="text-lg font-bold">Known recordings without a free source</h3>
              <p className="mb-3 text-sm text-muted">These exist (per MusicBrainz) but no source we use is authorized to stream them for free, so they can&apos;t be played here.</p>
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
        </>
      )}
    </section>
  )
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const tab = params.get('type') || 'all'
  const sort = params.get('sort') || 'relevance'
  const genre = params.get('genre') || ''
  const language = params.get('lang') || ''
  const [page, setPage] = useState(1)
  const debounced = useDebounce(q.trim(), 250)
  const slow = useDebounce(q.trim(), 700) // provider searches cost quota: wait until typing settles
  const genres = useApi(() => catalogApi.genres(), [])
  const languages = useLanguages()

  const set = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
    setPage(1)
  }

  const results = useApi((signal) => debounced
    ? catalogApi.search({ q: debounced, type: tab === 'all' ? undefined : tab, sort, genre: genre || undefined,
      page, page_size: tab === 'all' ? 6 : 20 }, signal)
    : Promise.resolve(null), [debounced, tab, sort, genre, page])

  if (!q.trim()) return <GenreGrid />
  const data = results.data
  const loading = results.loading || debounced !== q.trim()
  const empty = data && ['songs', 'artists', 'albums', 'playlists'].every((k) => !data[k] || data[k].total === 0)
  const showOpen = (tab === 'all' || tab === 'song') && page === 1
  const localIds = new Set((data?.songs?.items || []).map((x) => x.id))

  return (
    <div className="px-4 md:px-6">
      <div className="mb-6 flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => set('type', t.id === 'all' ? '' : t.id)} aria-pressed={tab === t.id}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${tab === t.id ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex gap-2">
          <select aria-label="Language for open-catalog results" value={language} onChange={(e) => set('lang', e.target.value)} className={`${inputClass} w-auto py-1.5`}>
            <option value="">Any language</option>
            {languages.filter((l) => l.featured || l.playable_count > 0).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>
          <select aria-label="Filter by genre" value={genre} onChange={(e) => set('genre', e.target.value)} className={`${inputClass} w-auto py-1.5`}>
            <option value="">All genres</option>
            {genres.data?.map((g) => <option key={g.id} value={g.slug}>{g.name}</option>)}
          </select>
          <select aria-label="Sort results" value={sort} onChange={(e) => set('sort', e.target.value === 'relevance' ? '' : e.target.value)} className={`${inputClass} w-auto py-1.5`}>
            <option value="relevance">Most relevant</option>
            <option value="popular">Most popular</option>
            <option value="newest">Newest</option>
            <option value="title">A–Z</option>
          </select>
        </div>
      </div>

      {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
      {loading && <div className="space-y-8"><TrackListSkeleton rows={4} /><CardGridSkeleton count={6} /></div>}
      {!loading && empty && (
        <EmptyState icon={SearchX} title={`Nothing in the catalog yet for "${q}"`}>
          {showOpen ? 'Checking the open catalogs below.' : 'Check the spelling, or try fewer or different keywords.'}
        </EmptyState>
      )}
      {!loading && data && !empty && (
        <div className="space-y-10">
          {data.songs?.total > 0 && (
            <section>
              <h2 className="mb-3 text-2xl font-bold">Songs <span className="text-base font-normal text-muted">({data.songs.total})</span></h2>
              <TrackList items={data.songs.items.map((song) => ({ song }))} context={{ type: 'search', name: `Search: ${q}` }} />
              {tab === 'song' && <Pager page={page} pages={data.songs.pages} onChange={setPage} />}
            </section>
          )}
          {data.artists?.total > 0 && (
            <section>
              <h2 className="mb-3 text-2xl font-bold">Artists</h2>
              <CardGrid>{data.artists.items.map((a) => <ArtistCard key={a.id} artist={a} />)}</CardGrid>
              {tab === 'artist' && <Pager page={page} pages={data.artists.pages} onChange={setPage} />}
            </section>
          )}
          {data.albums?.total > 0 && (
            <section>
              <h2 className="mb-3 text-2xl font-bold">Albums</h2>
              <CardGrid>{data.albums.items.map((a) => <AlbumCard key={a.id} album={a} />)}</CardGrid>
              {tab === 'album' && <Pager page={page} pages={data.albums.pages} onChange={setPage} />}
            </section>
          )}
          {data.playlists?.total > 0 && (
            <section>
              <h2 className="mb-3 text-2xl font-bold">Playlists</h2>
              <CardGrid>{data.playlists.items.map((p) => <PlaylistCard key={p.id} playlist={p} />)}</CardGrid>
              {tab === 'playlist' && <Pager page={page} pages={data.playlists.pages} onChange={setPage} />}
            </section>
          )}
        </div>
      )}
      {showOpen && slow && slow === q.trim() && (
        <div className="mt-10"><OpenCatalogResults q={slow} language={language} localIds={localIds} /></div>
      )}
    </div>
  )
}
