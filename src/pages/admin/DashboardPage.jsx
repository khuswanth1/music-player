import { useState } from 'react'
import { adminApi } from '../../api/endpoints'
import { ErrorState, Skeleton } from '../../components/ui'
import { useApi } from '../../hooks/useApi'
import { formatMoney, formatNumber } from '../../lib/format'

function Stat({ label, value, tone }) {
  return (
    <div className="rounded-lg bg-surface p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-subtle">{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${tone === 'danger' ? 'text-danger' : ''}`}>{value}</p>
    </div>
  )
}

/** Minimal accessible bar chart (no chart library needed for daily series). */
export function BarChart({ title, series, format = formatNumber, color = 'var(--color-accent)' }) {
  const max = Math.max(1, ...series.map((p) => p.value))
  const total = series.reduce((s, p) => s + p.value, 0)
  const [hover, setHover] = useState(null)
  return (
    <figure className="rounded-lg bg-surface p-4">
      <figcaption className="mb-3 flex items-baseline justify-between">
        <span className="font-bold">{title}</span>
        <span className="text-sm tabular-nums text-muted">{hover ? `${hover.date}: ${format(hover.value)}` : `Total ${format(total)}`}</span>
      </figcaption>
      <div className="flex h-36 items-end gap-[2px]" role="img" aria-label={`${title}: total ${format(total)} over ${series.length} days`}>
        {series.map((p) => (
          <div key={p.date} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(p)} onMouseLeave={() => setHover(null)}>
            <div className="w-full rounded-t-sm transition-opacity hover:opacity-80"
              style={{ height: `${Math.max(p.value ? 4 : 1, (p.value / max) * 100)}%`, background: p.value ? color : '#2c2c36' }} />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-subtle"><span>{series[0]?.date}</span><span>{series.at(-1)?.date}</span></div>
    </figure>
  )
}

function Ranked({ title, items }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <section className="rounded-lg bg-surface p-4">
      <h3 className="mb-3 font-bold">{title}</h3>
      {items.length === 0 && <p className="text-sm text-muted">No plays in this period.</p>}
      <ol className="space-y-2">
        {items.map((it, i) => (
          <li key={it.id} className="text-sm">
            <div className="flex justify-between gap-2"><span className="truncate">{i + 1}. {it.name}{it.subtitle && <span className="text-muted"> · {it.subtitle}</span>}</span><span className="tabular-nums text-muted">{formatNumber(it.value)}</span></div>
            <div className="mt-1 h-1 rounded bg-line"><div className="h-full rounded bg-accent" style={{ width: `${(it.value / max) * 100}%` }} /></div>
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function DashboardPage() {
  const [days, setDays] = useState(30)
  const stats = useApi(() => adminApi.stats(), [])
  const analytics = useApi(() => adminApi.analytics(days), [days])
  if (stats.error) return <ErrorState error={stats.error} onRetry={stats.reload} />
  const s = stats.data
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {stats.loading ? [...Array(6)].map((_, i) => <Skeleton key={i} className="h-20" />) : (
          <>
            <Stat label="Users" value={formatNumber(s.users)} />
            <Stat label="Active (30 d)" value={formatNumber(s.active_users_30d)} />
            <Stat label="Premium" value={formatNumber(s.premium_users)} />
            <Stat label="Plays (24 h)" value={formatNumber(s.plays_24h)} />
            <Stat label="Revenue (30 d)" value={formatMoney(s.revenue_30d_cents)} />
            <Stat label="Failed webhooks" value={s.failed_webhooks} tone={s.failed_webhooks ? 'danger' : undefined} />
            <Stat label="Songs" value={s.songs} />
            <Stat label="Albums" value={s.albums} />
            <Stat label="Artists" value={s.artists} />
            <Stat label="Playlists" value={s.playlists} />
            <Stat label="Total plays" value={formatNumber(s.plays_total)} />
          </>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted">Period:</span>
        {[7, 30, 90].map((d) => (
          <button key={d} onClick={() => setDays(d)} aria-pressed={days === d}
            className={`rounded-full px-3 py-1 text-sm font-semibold ${days === d ? 'bg-white text-black' : 'bg-elevated'}`}>{d} days</button>
        ))}
      </div>
      {analytics.error && <ErrorState error={analytics.error} onRetry={analytics.reload} />}
      {analytics.loading ? <Skeleton className="h-48" /> : analytics.data && (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <BarChart title="Plays per day" series={analytics.data.plays} />
            <BarChart title="Sign-ups per day" series={analytics.data.signups} color="#38bdf8" />
            <BarChart title="Revenue per day" series={analytics.data.revenue_cents} format={(v) => formatMoney(v)} color="#fbbf24" />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Ranked title="Top songs" items={analytics.data.top_songs} />
            <Ranked title="Top artists" items={analytics.data.top_artists} />
            <section className="rounded-lg bg-surface p-4">
              <h3 className="mb-3 font-bold">Active plans</h3>
              {Object.entries(analytics.data.plan_breakdown).map(([plan, n]) => (
                <p key={plan} className="flex justify-between py-1 text-sm"><span>{plan.replace('premium_', 'Premium ')}</span><span className="tabular-nums">{n}</span></p>
              ))}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
