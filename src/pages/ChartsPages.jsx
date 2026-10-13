import { Link, useParams } from 'react-router'
import { ExternalLink, Trophy } from 'lucide-react'
import { musicApi } from '../api/endpoints'
import { PlayFab } from '../components/Cards'
import TrackList from '../components/TrackList'
import { EmptyState, ErrorState, Skeleton, TrackListSkeleton } from '../components/ui'
import { usePlayer } from '../context/PlayerContext'
import { useApi } from '../hooks/useApi'
import { plural } from '../lib/format'
import { useProviders } from '../lib/languages'

const KIND_TITLES = { global: null, region: 'Regions', language: 'Languages' }
const GRADIENTS = ['from-amber-500 to-rose-700', 'from-emerald-500 to-sky-800', 'from-fuchsia-500 to-indigo-800',
  'from-sky-500 to-violet-800', 'from-lime-500 to-emerald-800', 'from-orange-500 to-red-800']

function ChartCard({ chart, index }) {
  return (
    <Link to={`/charts/${encodeURIComponent(chart.id)}`}
      className={`flex min-h-36 flex-col justify-between gap-3 rounded-lg bg-gradient-to-br p-4 transition hover:scale-[1.02] ${GRADIENTS[index % GRADIENTS.length]}`}>
      <Trophy className="size-6 text-white/80" />
      <div>
        <p className="text-lg font-extrabold leading-tight">{chart.title}</p>
        <p className="text-xs text-white/80">{chart.subtitle} · {plural(chart.track_count, 'track')}</p>
      </div>
    </Link>
  )
}

export function ChartsPage() {
  const { data, error, loading, reload } = useApi(() => musicApi.charts(), [])
  if (error) return <ErrorState error={error} onRetry={reload} />
  const groups = Object.keys(KIND_TITLES).map((kind) => [kind, (data || []).filter((c) => c.kind === kind)])

  return (
    <div className="px-4 md:px-6">
      <h1 className="text-3xl font-extrabold">Charts</h1>
      <p className="mt-2 max-w-2xl text-sm text-muted">
        Built only from data we have: listens on this service over the last 7 days, then each source&apos;s own popularity.
        Regions and languages appear once they have playable tracks.
      </p>
      {loading ? (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : (
        groups.map(([kind, charts]) => charts.length > 0 && (
          <section key={kind} className="mt-8">
            {KIND_TITLES[kind] && <h2 className="mb-3 text-xl font-bold">{KIND_TITLES[kind]}</h2>}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {charts.map((c, i) => <ChartCard key={c.id} chart={c} index={i} />)}
            </div>
          </section>
        ))
      )}
    </div>
  )
}

export function ChartPage() {
  const { id } = useParams()
  const { data, error, loading, reload } = useApi(() => musicApi.chart(id), [id])
  const { playList, context, isPlaying, toggle } = usePlayer()
  if (error) return <ErrorState error={error} onRetry={reload} />
  const songs = data?.entries.map((e) => e.song) || []
  const active = context?.type === 'chart' && context?.id === id

  return (
    <div>
      <div className="-mt-16 bg-gradient-to-b from-amber-700/80 to-transparent px-4 pb-6 pt-24 md:px-6">
        <p className="text-sm font-semibold">Chart</p>
        {loading ? <Skeleton className="mt-2 h-14 w-1/2" /> : <h1 className="mt-1 text-4xl font-black tracking-tight md:text-6xl">{data.title}</h1>}
        {data && <p className="mt-3 max-w-2xl text-xs text-zinc-200">{data.basis}</p>}
      </div>
      <div className="flex items-center gap-6 px-4 py-4 md:px-6">
        <PlayFab label="Play chart" playing={active && isPlaying} className="size-14"
          onClick={() => (active ? toggle() : songs.length && playList(songs, 0, { type: 'chart', id, name: data?.title }))} />
      </div>
      <div className="px-2 md:px-4">
        {loading ? <TrackListSkeleton rows={10} /> : songs.length ? (
          <TrackList items={songs.map((song) => ({ song }))} context={{ type: 'chart', id, name: data.title }} />
        ) : <EmptyState icon={Trophy} title="Nothing on this chart yet">Charts fill in as tracks are fetched and played.</EmptyState>}
      </div>
    </div>
  )
}

const POLICY = (p) => [
  p.policy.stream ? 'Streams through the source’s own authorized URLs' : 'Metadata only — never streamed',
  p.policy.requires_open_license ? 'Only tracks with a verified Creative Commons / public-domain license' : 'Streaming permitted by the source’s API terms; rights stay with the artist',
  p.policy.download_links ? 'Download links when both the license and the source allow it' : 'No downloads',
]

export function SourcesPage() {
  const providers = useProviders()
  return (
    <div className="max-w-4xl px-4 md:px-6">
      <h1 className="text-3xl font-extrabold">Sources &amp; licenses</h1>
      <p className="mt-3 text-sm text-muted">
        All music here is either hosted with the rights holder&apos;s permission or streamed from a source whose terms let other
        apps play it for free. Each track shows its source, license and attribution — open a track&apos;s menu and choose
        <span className="text-white"> Credits &amp; license</span>. Tracks whose rights can&apos;t be verified are shown as
        unavailable and are never played. We don&apos;t offer every song in the world: only what these sources make available.
      </p>

      <div className="mt-8 space-y-4">
        {providers.map((p) => (
          <section key={p.key} className="rounded-lg bg-surface p-5">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-xl font-bold">{p.name}</h2>
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold uppercase ${p.enabled ? 'bg-accent/15 text-accent' : 'bg-zinc-700 text-zinc-300'}`}>
                {p.enabled ? 'Active' : p.requires_credentials && !p.configured ? 'Needs an API key' : 'Inactive'}
              </span>
              {p.track_count > 0 && <span className="text-xs text-muted">{plural(p.playable_count, 'playable track')} in the catalog</span>}
            </div>
            <p className="mt-2 text-sm text-zinc-300">{p.description}</p>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
              {POLICY(p).map((line) => <li key={line}>{line}</li>)}
              {p.policy.notes && <li>{p.policy.notes}</li>}
            </ul>
            <div className="mt-3 flex flex-wrap gap-4 text-sm">
              <a href={p.homepage} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">Visit {p.name} <ExternalLink className="size-3.5" /></a>
              <a href={p.terms_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-muted hover:text-white hover:underline">Terms <ExternalLink className="size-3.5" /></a>
            </div>
          </section>
        ))}
      </div>

      <section className="mt-10 rounded-lg p-5 ring-1 ring-line">
        <h2 className="text-lg font-bold">What this costs</h2>
        <p className="mt-2 text-sm text-muted">
          This service pays no music licensing fees and is free to use. Running it still has costs: hosting, bandwidth,
          and any paid tiers of third-party APIs if usage grows beyond their free quotas. Some sources (e.g. Jamendo&apos;s free
          API) are for non-commercial use only; a commercial deployment needs their commercial terms, and non-commercial
          (NC) licensed tracks are then switched off automatically.
        </p>
      </section>
    </div>
  )
}
