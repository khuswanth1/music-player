import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { BookmarkPlus, BookmarkCheck, ExternalLink, Heart, Mic2, Pause, Play, Rss, SearchX } from 'lucide-react'
import { podcastApi } from '../api/endpoints'
import { CardGrid, MediaCard } from '../components/Cards'
import { ProviderStatusList } from '../components/ProviderStatus'
import { Button, CardGridSkeleton, Cover, EmptyState, ErrorState, PageSkeleton, Spinner, inputClass, selectClass } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useToast } from '../context/ToastContext'
import { useApi, useDebounce } from '../hooks/useApi'
import { formatDate, formatDuration } from '../lib/format'
import { useLanguages } from '../lib/languages'
import { episodeToItem } from '../lib/tracks'
import { AccessBadge } from '../components/TrackMeta'
import { CollectionHeader } from './CatalogPages'

const COUNTRY_STORES = [
  ['US', 'United States'], ['IN', 'India'], ['GB', 'United Kingdom'], ['CA', 'Canada'], ['AU', 'Australia'], ['JP', 'Japan'],
  ['KR', 'South Korea'], ['CN', 'China'], ['BR', 'Brazil'], ['DE', 'Germany'], ['FR', 'France'], ['ES', 'Spain'], ['MX', 'Mexico'],
  ['IT', 'Italy'], ['AE', 'United Arab Emirates'], ['ZA', 'South Africa'], ['NG', 'Nigeria'], ['ID', 'Indonesia'],
]

export function PodcastCard({ podcast }) {
  return (
    <MediaCard to={`/podcast/${encodeURIComponent(podcast.id)}`} image={podcast.image_url} seed={podcast.id} title={podcast.title}
      subtitle={[podcast.publisher, podcast.language ? podcast.language.toUpperCase() : null].filter(Boolean).join(' · ')} />
  )
}

export function EpisodeRow({ episode, queue, onChange, showPodcast = false }) {
  const { current, isPlaying, playList, toggle } = usePlayer()
  const toast = useToast()
  const active = current?.id === episode.id
  const [toggled, setSaved] = useState(null) // null until the listener changes it here; then it wins over the server's value
  const saved = toggled ?? Boolean(episode.saved)
  const progress = episode.duration_s && episode.position_s ? Math.min(100, (episode.position_s / episode.duration_s) * 100) : 0

  const play = () => {
    if (!episode.playable) return
    if (active) return toggle()
    const items = (queue || [episode]).filter((e) => e.playable).map(episodeToItem)
    const at = Math.max(0, items.findIndex((i) => i.id === episode.id))
    playList(items, at, { type: 'podcast', id: episode.podcast_id, name: episode.podcast_title })
  }

  const toggleSave = async () => {
    try {
      await (saved ? podcastApi.unsave(episode) : podcastApi.save(episode))
      setSaved(!saved)
      onChange?.()
      toast.success(saved ? 'Removed from saved episodes' : 'Episode saved')
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <article className="flex gap-4 rounded-lg p-3 hover:bg-white/5">
      <Cover src={episode.image_url} seed={episode.podcast_id} alt="" className="size-20 shrink-0" />
      <div className="min-w-0 flex-1">
        {showPodcast && <Link to={`/podcast/${encodeURIComponent(episode.podcast_id)}`} className="text-xs text-muted hover:underline">{episode.podcast_title}</Link>}
        <h3 className={`font-bold ${active ? 'text-accent' : ''}`}>{episode.title}</h3>
        {episode.description && <p className="mt-1 line-clamp-2 text-sm text-muted">{episode.description}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
          <button onClick={play} disabled={!episode.playable} aria-label={`${active && isPlaying ? 'Pause' : 'Play'} ${episode.title}`}
            className="flex items-center gap-1.5 rounded-full bg-white px-3 py-1 font-bold text-black hover:scale-105 disabled:opacity-40">
            {active && isPlaying ? <Pause className="size-3.5" fill="currentColor" /> : <Play className="size-3.5" fill="currentColor" />}
            {active && isPlaying ? 'Pause' : episode.completed ? 'Play again' : episode.position_s > 30 ? 'Resume' : 'Play'}
          </button>
          <span>{formatDate(episode.published_at)}</span>
          {episode.duration_s > 0 && <span>{formatDuration(episode.duration_s * 1000)}</span>}
          {episode.season != null && <span>S{episode.season}{episode.episode != null ? ` E${episode.episode}` : ''}</span>}
          {episode.explicit && <span className="rounded-sm bg-zinc-400 px-1 font-bold text-black">E</span>}
          {episode.playable ? <AccessBadge song={{ access: 'podcast' }} /> : <span className="text-amber-300">No playable audio</span>}
          {episode.completed && <span className="text-accent">Played</span>}
          <button onClick={toggleSave} aria-pressed={saved} aria-label={saved ? 'Remove from saved episodes' : 'Save episode'}
            className={`ml-auto ${saved ? 'text-accent' : 'hover:text-white'}`}>
            {saved ? <BookmarkCheck className="size-5" /> : <BookmarkPlus className="size-5" />}
          </button>
          {episode.source_url && <a href={episode.source_url} target="_blank" rel="noopener noreferrer" aria-label="Episode page" className="hover:text-white"><ExternalLink className="size-4" /></a>}
        </div>
        {progress > 0 && !episode.completed && (
          <div className="mt-2 h-1 w-full max-w-xs rounded bg-zinc-700" role="progressbar" aria-valuenow={Math.round(progress)} aria-valuemin={0} aria-valuemax={100} aria-label="Listening progress">
            <div className="h-full rounded bg-accent" style={{ width: `${progress}%` }} />
          </div>
        )}
      </div>
    </article>
  )
}

const TABS = [['discover', 'Discover'], ['following', 'Following'], ['latest', 'Latest episodes'], ['saved', 'Saved'], ['history', 'History']]

function Following() {
  const { data, loading, error, reload } = useApi(() => podcastApi.following(), [])
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading) return <CardGridSkeleton />
  if (!data.length) return <EmptyState icon={Mic2} title="No followed podcasts yet">Follow a show from Discover and its new episodes will show up under “Latest episodes”.</EmptyState>
  return <CardGrid>{data.map((p) => <PodcastCard key={p.id} podcast={p} />)}</CardGrid>
}

function EpisodeList({ load, empty, showPodcast = true }) {
  const { data, loading, error, reload } = useApi(load, [])
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading) return <p className="flex items-center gap-2 py-6 text-muted"><Spinner className="size-4" /> Loading…</p>
  if (!data.length) return <EmptyState icon={Mic2} title={empty.title}>{empty.text}</EmptyState>
  return <div className="space-y-1">{data.map((e) => <EpisodeRow key={e.id} episode={e} queue={data} showPodcast={showPodcast} onChange={reload} />)}</div>
}

function History() {
  const { data, loading, error, reload } = useApi(() => podcastApi.history(), [])
  const { playList } = usePlayer()
  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading) return <p className="flex items-center gap-2 py-6 text-muted"><Spinner className="size-4" /> Loading…</p>
  if (!data.items.length) return <EmptyState icon={Mic2} title="Nothing here yet">Episodes you listen to appear here, and pick up where you left off.</EmptyState>
  const play = (h) => playList([episodeToItem({ id: h.episode_id, podcast_id: h.podcast_id, title: h.title, podcast_title: h.podcast_title,
    image_url: h.image_url, audio_url: h.audio_url, duration_s: h.duration_s, position_s: h.position_s, completed: h.completed, playable: Boolean(h.audio_url) })],
  0, { type: 'podcast', id: h.podcast_id, name: h.podcast_title })
  return (
    <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
      {data.items.map((h) => (
        <li key={h.episode_id} className="flex items-center gap-3 p-3">
          <Cover src={h.image_url} seed={h.podcast_id} alt="" className="size-12 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{h.title}</p>
            <Link to={`/podcast/${encodeURIComponent(h.podcast_id)}`} className="truncate text-sm text-muted hover:underline">{h.podcast_title}</Link>
          </div>
          <span className="hidden text-xs text-muted sm:block">{h.completed ? 'Played' : `${formatDuration(h.position_s * 1000)} / ${h.duration_s ? formatDuration(h.duration_s * 1000) : '?'}`}</span>
          <button onClick={() => play(h)} disabled={!h.audio_url} aria-label={`Play ${h.title}`} className="rounded-full bg-white p-2 text-black hover:scale-105 disabled:opacity-40"><Play className="size-4" fill="currentColor" /></button>
        </li>
      ))}
    </ul>
  )
}

function Discover() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const country = params.get('country') || ''
  const language = params.get('lang') || ''
  const category = params.get('cat') || ''
  const languages = useLanguages()
  const categories = useApi(() => podcastApi.categories(), [])
  const debounced = useDebounce(q.trim(), 450)
  const set = (key, value) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const results = useApi((signal) => podcastApi.search({ q: debounced, country: country || undefined, language: language || undefined,
    category: category || undefined }, signal), [debounced, country, language, category])
  const data = results.data

  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-2">
        <input type="search" value={q} onChange={(e) => set('q', e.target.value)} placeholder="Search podcasts" aria-label="Search podcasts"
          className={`${inputClass} max-w-xs flex-1`} />
        <select aria-label="Country (Apple Podcasts store)" value={country} onChange={(e) => set('country', e.target.value)} className={`${selectClass}`}>
          <option value="">Any country</option>
          {COUNTRY_STORES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select>
        <select aria-label="Language" value={language} onChange={(e) => set('lang', e.target.value)} className={`${selectClass}`}>
          <option value="">Any language</option>
          {languages.filter((l) => l.featured).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
        </select>
      </div>
      <div className="mb-5 flex flex-wrap gap-2" role="group" aria-label="Categories">
        <button onClick={() => set('cat', '')} aria-pressed={!category} className={`rounded-full px-3 py-1.5 text-sm font-semibold ${!category ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>All</button>
        {categories.data?.map((c) => (
          <button key={c.id} onClick={() => set('cat', c.id)} aria-pressed={category === c.id}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${category === c.id ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>{c.name}</button>
        ))}
      </div>
      {results.error && <ErrorState error={results.error} onRetry={results.reload} />}
      {results.loading && <CardGridSkeleton />}
      {data && !results.loading && (
        <>
          <p className="mb-3 text-sm text-muted">{data.basis}</p>
          <ProviderStatusList providers={data.providers} className="mb-4" />
          {data.podcasts.length === 0
            ? <EmptyState icon={SearchX} title="No podcasts found">{language ? 'Only shows whose publisher states this language are listed. Try another language or no language filter.' : 'Try different keywords or another country.'}</EmptyState>
            : <CardGrid>{data.podcasts.map((p) => <PodcastCard key={p.id} podcast={p} />)}</CardGrid>}
        </>
      )}
    </div>
  )
}

export function PodcastsPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'discover'
  const setTab = (id) => {
    const next = new URLSearchParams(params)
    next.set('tab', id)
    setParams(next, { replace: true })
  }
  return (
    <div className="px-4 md:px-6">
      <h1 className="mb-1 text-3xl font-extrabold tracking-tight">Podcasts</h1>
      <p className="mb-5 text-sm text-muted">Shows and episodes from Apple Podcasts, Podcast Index and Listen Notes (where configured), played from each publisher&apos;s own RSS audio.</p>
      <div className="mb-6 flex flex-wrap gap-2" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={`rounded-full px-4 py-1.5 text-sm font-semibold ${tab === id ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>{label}</button>
        ))}
      </div>
      {tab === 'discover' && <Discover />}
      {tab === 'following' && <Following />}
      {tab === 'latest' && <EpisodeList load={() => podcastApi.latestFollowed()} empty={{ title: 'No new episodes', text: 'Follow some podcasts to see their newest episodes here.' }} />}
      {tab === 'saved' && <EpisodeList load={() => podcastApi.saved()} empty={{ title: 'No saved episodes', text: 'Use the bookmark on an episode to keep it here.' }} />}
      {tab === 'history' && <History />}
    </div>
  )
}

export function PodcastPage() {
  const { id } = useParams()
  const toast = useToast()
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const search = useDebounce(q.trim(), 300)
  const { data, loading, error, reload, setData } = useApi((signal) => podcastApi.episodes(id, { page, page_size: 25, q: search || undefined }, signal), [id, page, search])
  const detail = useApi(() => podcastApi.get(id), [id])
  const podcast = data?.podcast
  const items = useMemo(() => data?.items || [], [data])

  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  if (loading && !data) return <PageSkeleton />

  const toggleFollow = async () => {
    try {
      await (podcast.followed ? podcastApi.unfollow(podcast.id) : podcastApi.follow(podcast))
      setData((d) => ({ ...d, podcast: { ...d.podcast, followed: !d.podcast.followed } }))
      toast.success(podcast.followed ? 'Unfollowed' : 'Following')
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <div>
      <CollectionHeader image={podcast.image_url} seed={podcast.id} kicker="Podcast" title={podcast.title}>
        {podcast.publisher && <span className="font-bold">{podcast.publisher}</span>}
        <span>{podcast.language ? `· ${podcast.language.toUpperCase()} ` : '· Language unknown '}{data.total ? `· ${data.total} episodes` : ''}</span>
      </CollectionHeader>
      <div className="flex flex-wrap items-center gap-4 px-4 py-4 md:px-6">
        <Button onClick={toggleFollow} variant={podcast.followed ? 'outline' : 'primary'}>
          <Heart className="size-4" fill={podcast.followed ? 'currentColor' : 'none'} /> {podcast.followed ? 'Following' : 'Follow'}
        </Button>
        {podcast.website && <a href={podcast.website} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm text-muted hover:text-white"><ExternalLink className="size-4" /> Website</a>}
        {podcast.feed_url && <a href={podcast.feed_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-sm text-muted hover:text-white"><Rss className="size-4" /> RSS</a>}
        <input type="search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Search episodes" aria-label="Search episodes" className={`${inputClass} ml-auto max-w-xs`} />
      </div>
      <div className="px-4 md:px-6">
        {podcast.description && <p className="mb-6 max-w-3xl text-sm text-zinc-300">{podcast.description}</p>}
        {detail.data?.providers?.some((p) => p.status !== 'ok') && <ProviderStatusList providers={detail.data.providers} className="mb-4" />}
        {items.length === 0
          ? <EmptyState icon={Mic2} title="No episodes found">{search ? 'No episode matches that search.' : "The publisher's feed has no episodes we can list."}</EmptyState>
          : <div className="space-y-1">{items.map((e) => <EpisodeRow key={e.id} episode={e} queue={items} />)}</div>}
        {data.pages > 1 && (
          <div className="mt-6 flex items-center justify-center gap-3 text-sm">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-full border border-line px-4 py-1.5 disabled:opacity-40">Previous</button>
            <span className="text-muted">Page {page} of {data.pages}</span>
            <button disabled={page >= data.pages} onClick={() => setPage(page + 1)} className="rounded-full border border-line px-4 py-1.5 disabled:opacity-40">Next</button>
          </div>
        )}
      </div>
    </div>
  )
}
