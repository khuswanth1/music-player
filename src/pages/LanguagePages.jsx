import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { Check, Download, Languages as LanguagesIcon, Plus, Search } from 'lucide-react'
import { musicApi } from '../api/endpoints'
import { PlayFab } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import TrackList from '../components/TrackList'
import { Button, EmptyState, ErrorState, Skeleton, TrackListSkeleton, inputClass } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { usePreferredLanguages } from '../hooks/usePreferredLanguages'
import { plural } from '../lib/format'
import { useProviders } from '../lib/languages'

function LanguageCard({ lang, starred, onStar }) {
  return (
    <div className="group relative rounded-lg bg-surface p-4 transition hover:bg-elevated">
      <Link to={`/language/${lang.code}`} className="block">
        <p dir={lang.rtl ? 'rtl' : undefined} className="truncate text-2xl font-extrabold" lang={lang.code}>{lang.native_name}</p>
        <p className="mt-1 truncate text-sm text-muted">{lang.name} · {lang.region_name}</p>
        <p className={`mt-3 text-xs font-semibold ${lang.playable_count ? 'text-accent' : 'text-subtle'}`}>
          {lang.playable_count ? plural(lang.playable_count, 'playable track') : 'Nothing fetched yet'}
        </p>
      </Link>
      {onStar && (
        <button onClick={() => onStar(lang.code)} aria-pressed={starred}
          aria-label={starred ? `Remove ${lang.name} from your languages` : `Add ${lang.name} to your languages`}
          className={`absolute right-3 top-3 rounded-full p-1.5 ${starred ? 'bg-accent text-black' : 'text-muted opacity-0 ring-1 ring-line hover:text-white group-hover:opacity-100 focus:opacity-100'}`}>
          {starred ? <Check className="size-3.5" /> : <Plus className="size-3.5" />}
        </button>
      )}
    </div>
  )
}

export function LanguagesPage() {
  const { data, error, loading, reload } = useApi(() => musicApi.languages(), [])
  const { preferred, toggle } = usePreferredLanguages()
  const [query, setQuery] = useState('')
  const [region, setRegion] = useState('')

  const regions = useMemo(() => {
    const seen = new Map()
    for (const l of data || []) seen.set(l.region, l.region_name)
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [data])

  if (error) return <ErrorState error={error} onRetry={reload} />
  const q = query.trim().toLowerCase()
  const matches = (data || []).filter((l) => (!region || l.region === region)
    && (!q || l.name.toLowerCase().includes(q) || l.native_name.toLowerCase().includes(q) || l.code === q))
  const mine = (data || []).filter((l) => preferred.includes(l.code))
  const withMusic = matches.filter((l) => l.playable_count > 0 || l.featured)
  const rest = matches.filter((l) => !(l.playable_count > 0 || l.featured))
  const total = (data || []).reduce((n, l) => n + l.playable_count, 0)
  const languagesWithMusic = (data || []).filter((l) => l.playable_count > 0).length

  return (
    <div className="px-4 md:px-6">
      <header className="mb-6">
        <h1 className="flex items-center gap-3 text-3xl font-extrabold"><LanguagesIcon className="size-8 text-accent" /> Languages</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          {loading ? 'Loading…' : `${plural(total, 'playable track')} across ${plural(languagesWithMusic, 'language')} so far, from open catalogs that allow free streaming.`}
          {' '}Counts reflect what the sources actually offer — opening a language fetches more. <Link to="/sources" className="underline hover:text-white">About the sources</Link>
        </p>
      </header>

      {mine.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-xl font-bold">Your languages</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {mine.map((l) => <LanguageCard key={l.code} lang={l} starred onStar={toggle} />)}
          </div>
        </section>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <label className="relative min-w-56 flex-1 sm:max-w-xs">
          <span className="sr-only">Find a language</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a language (e.g. Telugu, 한국어)"
            className={`${inputClass} pl-9`} />
        </label>
        <select aria-label="Filter by region" value={region} onChange={(e) => setRegion(e.target.value)} className={`${inputClass} w-auto py-2`}>
          <option value="">All regions</option>
          {regions.map(([key, name]) => <option key={key} value={key}>{name}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{[...Array(10)].map((_, i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {withMusic.map((l) => <LanguageCard key={l.code} lang={l} starred={preferred.includes(l.code)} onStar={toggle} />)}
          </div>
          {rest.length > 0 && (
            <section className="mt-10">
              <h2 className="mb-1 text-xl font-bold">More languages</h2>
              <p className="mb-4 text-sm text-muted">Every language is supported; these don&apos;t have tracks in the catalog yet. Open one to search the sources.</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3 lg:grid-cols-5">
                {rest.map((l) => (
                  <Link key={l.code} to={`/language/${l.code}`} className="truncate rounded px-2 py-1.5 text-sm text-muted hover:bg-hover hover:text-white">
                    <span dir={l.rtl ? 'rtl' : undefined} lang={l.code}>{l.native_name}</span> <span className="text-subtle">· {l.name}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}
          {!matches.length && <EmptyState title="No language matches">Try its English or native name, or its ISO code.</EmptyState>}
        </>
      )}
    </div>
  )
}

const SORTS = [{ id: 'popular', label: 'Most popular' }, { id: 'newest', label: 'Recently added' }, { id: 'title', label: 'A–Z' }]

export function LanguagePage() {
  const { code } = useParams()
  const toast = useToast()
  const { playList, context, isPlaying, toggle: togglePlay } = usePlayer()
  const { preferred, toggle } = usePreferredLanguages()
  const providers = useProviders()
  const [genre, setGenre] = useState('')
  const [sort, setSort] = useState('popular')
  const [showAll, setShowAll] = useState(false)
  const [page, setPage] = useState(1)
  const [fetching, setFetching] = useState(false)
  const [fetchResult, setFetchResult] = useState(null)

  const info = useApi(() => musicApi.language(code), [code])
  const tracks = useApi((signal) => musicApi.languageTracks(code, { genre: genre || undefined, sort, page, page_size: 50,
    playable_only: !showAll }, signal), [code, genre, sort, showAll, page])

  // The first page may have just pulled tracks from the providers: refresh the counts in the header.
  const reloadInfo = info.reload
  const firstPageLoaded = page === 1 && !tracks.loading && tracks.data
  useEffect(() => {
    if (firstPageLoaded) reloadInfo({ silent: true })
  }, [firstPageLoaded, reloadInfo])

  if (info.error) return <ErrorState error={info.error} onRetry={info.reload} />
  const lang = info.data
  const items = tracks.data?.items || []
  const playable = items.filter((s) => s.playable)
  const active = context?.type === 'language' && context?.id === code

  const fetchMore = async () => {
    setFetching(true)
    try {
      const res = await musicApi.fetchLanguage(code)
      setFetchResult(res)
      toast.success(res.imported ? `Added ${plural(res.imported, 'new track')}` : 'No new tracks this time')
      info.reload({ silent: true })
      tracks.reload({ silent: true })
    } catch (err) {
      toast.apiError(err)
    } finally {
      setFetching(false)
    }
  }

  return (
    <div>
      <div className="-mt-16 bg-gradient-to-b from-emerald-800/80 to-transparent px-4 pb-6 pt-24 md:px-6">
        <p className="text-sm font-semibold">Language</p>
        {lang ? (
          <>
            <h1 dir={lang.rtl ? 'rtl' : undefined} lang={lang.code} className="mt-1 break-words text-5xl font-black tracking-tight md:text-7xl">{lang.native_name}</h1>
            <p className="mt-3 text-sm text-zinc-200">
              {lang.name} · {lang.region_name} · {plural(lang.playable_count, 'playable track')}
              {lang.track_count > lang.playable_count && ` (${lang.track_count - lang.playable_count} restricted)`}
            </p>
            {Object.keys(lang.sources).length > 0 && (
              <p className="mt-1 text-xs text-zinc-300">From {Object.entries(lang.sources).map(([k, n]) => `${providers.find((p) => p.key === k)?.name || k} (${n})`).join(', ')}</p>
            )}
          </>
        ) : <Skeleton className="mt-2 h-16 w-2/3" />}
      </div>

      <div className="flex flex-wrap items-center gap-4 px-4 py-4 md:px-6">
        <PlayFab label={`Play ${lang?.name || ''} tracks`} playing={active && isPlaying}
          onClick={() => (active ? togglePlay() : playable.length && playList(playable, 0, { type: 'language', id: code, name: lang?.name }))}
          className="size-14" />
        {lang && (
          <Button variant="outline" onClick={() => toggle(lang.code)} aria-pressed={preferred.includes(lang.code)}>
            {preferred.includes(lang.code) ? <><Check className="size-4" /> In your languages</> : <><Plus className="size-4" /> Add to your languages</>}
          </Button>
        )}
        <Button variant="ghost" onClick={fetchMore} loading={fetching}><Download className="size-4" /> Find more from open catalogs</Button>
      </div>
      {fetchResult && <ProviderStatusList providers={fetchResult.providers} className="px-4 pb-4 md:px-6" />}

      <div className="flex flex-wrap items-center gap-2 px-4 pb-4 md:px-6">
        <button onClick={() => { setGenre(''); setPage(1) }} aria-pressed={!genre}
          className={`rounded-full px-3 py-1.5 text-sm font-semibold ${!genre ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>All</button>
        {lang?.top_genres.map((g) => (
          <button key={g.id} onClick={() => { setGenre(g.slug); setPage(1) }} aria-pressed={genre === g.slug}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${genre === g.slug ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>
            {g.name} <span className="text-xs opacity-60">{g.track_count}</span>
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={showAll} onChange={(e) => { setShowAll(e.target.checked); setPage(1) }} className="accent-[var(--color-accent)]" />
            Show unavailable
          </label>
          <select aria-label="Sort tracks" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }} className={`${inputClass} w-auto py-1.5`}>
            {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      </div>

      <div className="px-2 md:px-4">
        {tracks.error && <ErrorState error={tracks.error} onRetry={tracks.reload} />}
        {tracks.loading ? <TrackListSkeleton rows={8} /> : items.length ? (
          <>
            <TrackList items={items.map((song) => ({ song }))} context={{ type: 'language', id: code, name: lang?.name }} />
            {tracks.data.pages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-3 text-sm">
                <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-full border border-line px-4 py-1.5 disabled:opacity-40">Previous</button>
                <span className="text-muted">Page {page} of {tracks.data.pages}</span>
                <button disabled={page >= tracks.data.pages} onClick={() => setPage(page + 1)} className="rounded-full border border-line px-4 py-1.5 disabled:opacity-40">Next</button>
              </div>
            )}
          </>
        ) : (
          <EmptyState icon={LanguagesIcon} title={`No playable ${lang?.name || ''} tracks yet`}
            action={<Button onClick={fetchMore} loading={fetching}>Search the open catalogs</Button>}>
            We only list music its source lets us stream for free. Some languages have little openly licensed music — the sources are checked again whenever you ask.
          </EmptyState>
        )}
      </div>
    </div>
  )
}
