import { useSearchParams } from 'react-router'
import { SearchX } from 'lucide-react'
import { worldApi } from '../api/endpoints'
import { CardGrid, MediaCard } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import { CardGridSkeleton, EmptyState, ErrorState, inputClass, selectClass } from '../components/ui'
import { useApi, useDebounce } from '../hooks/useApi'
import { languageName, useLanguages } from '../lib/languages'

export function ArtistResultCard({ artist }) {
  const languages = useLanguages()
  const meta = [
    artist.languages.slice(0, 2).map((c) => languageName(languages, c)).join(', ') || null,
    artist.playable_count ? `${artist.playable_count} playable` : artist.song_count ? 'Metadata only' : null,
    artist.country,
  ].filter(Boolean)
  return <MediaCard to={`/artist/${artist.id}`} image={artist.image_url || artist.image_fallback} seed={artist.id} title={artist.name} round id={artist.id}
    subtitle={meta.join(' · ') || 'Artist'} />
}

export default function ArtistsPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const language = params.get('lang') || ''
  const languages = useLanguages()
  const debounced = useDebounce(q.trim(), 500)
  const set = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const searching = debounced.length >= 2
  const results = useApi((signal) => (searching
    ? worldApi.searchArtists({ q: debounced, language: language || undefined }, signal)
    : worldApi.catalogArtists({ language: language || undefined, limit: 24 }, signal)), [debounced, language, searching])
  const items = searching ? results.data?.items : results.data

  return (
    <div className="px-4 md:px-6">
      <h1 className="mb-1 text-3xl font-extrabold tracking-tight">Artists &amp; singers</h1>
      <p className="mb-5 text-sm text-muted">Search live across the music sources. Artists you find join the catalog with whatever songs the sources let us play.</p>
      <div className="mb-6 flex flex-wrap gap-2">
        <input type="search" value={q} onChange={(e) => set('q', e.target.value)} placeholder="Search singers and artists" aria-label="Search artists" className={`${inputClass} max-w-md flex-1`} />
        <select aria-label="Language" value={language} onChange={(e) => set('lang', e.target.value)} className={`${selectClass}`}>
          <option value="">Any language</option>
          {languages.filter((l) => l.featured || l.playable_count > 0).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
      </div>
      {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
      {results.loading && <CardGridSkeleton />}
      {items && !results.loading && (
        <>
          {searching ? <ProviderStatusList providers={results.data.providers} className="mb-4" /> : (
            <p className="mb-3 text-sm text-muted">In this catalog, ranked by playable music and listens here — not a provider popularity chart.</p>
          )}
          {items.length === 0
            ? <EmptyState icon={SearchX} title="No artists found">{searching ? 'Check the spelling or try another language filter.' : 'Search for an artist to bring their music into the catalog.'}</EmptyState>
            : <CardGrid>{items.map((a) => <ArtistResultCard key={a.id} artist={a} />)}</CardGrid>}
        </>
      )}
    </div>
  )
}
