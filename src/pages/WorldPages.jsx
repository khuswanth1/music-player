import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Globe2 } from 'lucide-react'
import { worldApi } from '../api/endpoints'
import { AlbumCard, CardGrid } from '../components/Cards'
import TrackList from '../components/TrackList'
import { Button, CardGridSkeleton, EmptyState, ErrorState, TrackListSkeleton, selectClass } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useLanguages } from '../lib/languages'

const DECADES = [2020, 2010, 2000, 1990, 1980, 1970, 1960, 1950]
const SOURCES = ['internet_archive', 'wikimedia_commons', 'audius', 'ccmixter', 'openverse', 'jamendo']
const PAGE = 24

/** Every album in the catalog, newest first, with the same filters as everywhere else. */
export function AlbumsPage() {
  const [params, setParams] = useSearchParams()
  const language = params.get('lang') || ''
  const decade = params.get('decade') || ''
  const source = params.get('source') || ''
  const languages = useLanguages()
  const [more, setMore] = useState({ key: '', items: [], page: 1, done: false, busy: false })
  const key = JSON.stringify([language, decade, source])
  const query = (page) => ({
    language: language || undefined, source: source || undefined, page, limit: PAGE,
    year_from: decade || undefined, year_to: decade ? Number(decade) + 9 : undefined,
  })
  const first = useApi((signal) => worldApi.albums(query(1), signal), [key])
  const extra = more.key === key ? more : { items: [], page: 1, done: false, busy: false }
  const items = [...(first.data || []), ...extra.items]
  const set = (k, v) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }
  const loadMore = async () => {
    setMore({ ...extra, key, busy: true })
    try {
      const next = await worldApi.albums(query(extra.page + 1))
      setMore({ key, items: [...extra.items, ...next], page: extra.page + 1, done: next.length < PAGE, busy: false })
    } catch {
      setMore({ ...extra, key, busy: false })
    }
  }

  return (
    <div className="px-4 md:px-6">
      <h1 className="mb-1 text-3xl font-extrabold tracking-tight">Albums</h1>
      <p className="mb-5 text-sm text-muted">Every album in the catalog, from every source. Search finds more; each track shows how much of it can be played.</p>
      <div className="mb-6 flex flex-wrap gap-2">
        <select aria-label="Language" value={language} onChange={(e) => set('lang', e.target.value)} className={selectClass}>
          <option value="">Any language</option>
          {languages.filter((l) => l.featured || l.playable_count > 0).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
        <select aria-label="Decade" value={decade} onChange={(e) => set('decade', e.target.value)} className={selectClass}>
          <option value="">Any year</option>
          {DECADES.map((d) => <option key={d} value={d}>{d}s</option>)}
        </select>
        <select aria-label="Source" value={source} onChange={(e) => set('source', e.target.value)} className={selectClass}>
          <option value="">Any source</option>
          {SOURCES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
        </select>
      </div>
      {first.error && <ErrorState error={first.error} onRetry={first.reload} />}
      {first.loading && <CardGridSkeleton />}
      {!first.loading && first.data && (items.length === 0
        ? <EmptyState title="No albums match">Try another filter, or search for an artist to bring their albums in.</EmptyState>
        : (
          <>
            <CardGrid>{items.map((a) => <AlbumCard key={a.id} album={a} />)}</CardGrid>
            {!extra.done && first.data.length >= PAGE && (
              <div className="mt-6 flex justify-center"><Button variant="outline" onClick={loadMore} loading={extra.busy}>Load more albums</Button></div>
            )}
          </>
        ))}
    </div>
  )
}

/** Countries that have music in the catalog, from the countries the sources state (release or artist country). */
export function CountriesPage() {
  const { data, loading, error, reload } = useApi(() => worldApi.countries(), [])
  if (error) return <ErrorState error={error} onRetry={reload} />
  const known = (data || []).filter((c) => c.code)
  const unknown = (data || []).find((c) => !c.code)
  return (
    <div className="px-4 md:px-6">
      <h1 className="mb-1 text-3xl font-extrabold tracking-tight">Music around the world</h1>
      <p className="mb-5 max-w-2xl text-sm text-muted">
        Countries come from what the sources state: a release country, or the artist&apos;s country as listed by MusicBrainz. Tracks with neither stay
        under Unknown rather than being guessed. You can browse by <Link to="/languages" className="underline hover:text-white">language</Link> too.
      </p>
      {loading ? <CardGridSkeleton /> : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {known.map((c) => (
            <Link key={c.code} to={`/country/${c.code}`} className="rounded-lg bg-surface p-4 transition hover:bg-elevated">
              <p className="text-lg font-bold">{c.name}</p>
              <p className="text-sm text-muted">{c.playable_count} playable · {c.track_count} tracks</p>
            </Link>
          ))}
          {unknown && unknown.track_count > 0 && (
            <Link to="/country/unknown" className="rounded-lg bg-surface p-4 transition hover:bg-elevated">
              <p className="text-lg font-bold">Unknown</p>
              <p className="text-sm text-muted">{unknown.playable_count} playable · {unknown.track_count} tracks</p>
            </Link>
          )}
        </div>
      )}
    </div>
  )
}

export function CountryPage() {
  const { code } = useParams()
  const languages = useLanguages()
  const [language, setLanguage] = useState('')
  const [sort, setSort] = useState('popular')
  const [page, setPage] = useState(1)
  const [acc, setAcc] = useState({ key: '', items: [] })
  const unknown = code === 'unknown'
  const key = JSON.stringify([code, language, sort])
  const countries = useApi(() => worldApi.countries(), [])
  const res = useApi((signal) => (unknown ? Promise.resolve(null)
    : worldApi.tracks({ country: code, language: language || undefined, sort, page, page_size: 25 }, signal)), [key, page])
  const name = unknown ? 'Unknown country' : countries.data?.find((c) => c.code === code)?.name || code

  // Accumulate pages for "Load more"; any filter change starts over.
  useEffect(() => {
    if (res.data) setAcc((a) => ({ key, items: a.key === key && page > 1 ? [...a.items, ...res.data.items] : res.data.items }))
  }, [res.data, key, page])
  const items = acc.key === key ? acc.items : []

  return (
    <div className="px-4 md:px-6">
      <p className="text-sm font-semibold text-muted"><Link to="/countries" className="hover:underline">Countries</Link> /</p>
      <h1 className="mb-4 flex items-center gap-3 text-3xl font-extrabold tracking-tight"><Globe2 className="size-8 text-accent" /> {name}</h1>
      {unknown ? <p className="text-sm text-muted">These tracks have no country on file. Use search or browse by language instead.</p> : (
        <>
          <div className="mb-5 flex flex-wrap gap-2">
            <select aria-label="Language" value={language} onChange={(e) => { setLanguage(e.target.value); setPage(1) }} className={selectClass}>
              <option value="">Any language</option>
              {languages.filter((l) => l.featured || l.playable_count > 0).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
            <select aria-label="Order" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }} className={selectClass}>
              <option value="popular">Most played</option>
              <option value="latest">Newest</option>
            </select>
          </div>
          {res.error && <ErrorState error={res.error} onRetry={res.reload} />}
          {items.length === 0 && res.loading && <TrackListSkeleton />}
          {items.length === 0 && !res.loading && !res.error && (
            <EmptyState title={`No tracks from ${name} yet`}>Search for an artist from there, or pick another country.</EmptyState>
          )}
          {items.length > 0 && (
            <>
              {res.data?.basis && <p className="mb-3 text-xs text-subtle">{res.data.basis}</p>}
              <TrackList items={items.map((song) => ({ song }))} context={{ type: 'country', id: code, name }} />
              {res.data && items.length < res.data.total && (
                <div className="mt-6 flex justify-center"><Button variant="outline" loading={res.loading} onClick={() => setPage(page + 1)}>Load more</Button></div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
