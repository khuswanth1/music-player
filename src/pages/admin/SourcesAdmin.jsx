import { useState } from 'react'
import { adminApi } from '../../api/endpoints'
import { ProviderStatusList } from '../../components/ProviderStatus'
import { Button, ErrorState, Field, TrackListSkeleton, inputClass } from '../../components/ui'
import { useToast } from '../../context/ToastContext'
import { useApi } from '../../hooks/useApi'
import { formatDate, timeAgo } from '../../lib/format'
import { useLanguages } from '../../lib/languages'
import { Table } from './AdminLayout'

export default function SourcesAdmin() {
  const { data, error, loading, reload } = useApi(() => adminApi.providers(), [])
  const languages = useLanguages()
  const toast = useToast()
  const [language, setLanguage] = useState('te')
  const [pages, setPages] = useState(1)
  const [syncing, setSyncing] = useState(false)
  const [result, setResult] = useState(null)

  const sync = async (e) => {
    e.preventDefault()
    setSyncing(true)
    try {
      const res = await adminApi.syncLanguage(language, pages)
      setResult(res)
      toast.success(`Imported ${res.imported}, refreshed ${res.updated}`)
      reload({ silent: true })
    } catch (err) {
      toast.apiError(err)
    } finally {
      setSyncing(false)
    }
  }

  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 text-xl font-bold">Providers</h2>
        {loading ? <TrackListSkeleton rows={6} /> : (
          <Table head={['Source', 'Status', 'Requests today', 'Errors today', 'Last error', 'Tracks (playable)']}>
            {data.map((p) => (
              <tr key={p.key}>
                <td className="px-4 py-2 font-semibold">{p.name}</td>
                <td className="px-4 py-2">{p.enabled ? <span className="text-accent">Active</span> : <span className="text-muted">{p.configured ? 'Disabled' : 'Not configured'}</span>}</td>
                <td className="px-4 py-2 tabular-nums">{p.usage.requests_today}{p.usage.daily_quota ? ` / ${p.usage.daily_quota}` : ''}</td>
                <td className="px-4 py-2 tabular-nums">{p.usage.errors_today}</td>
                <td className="max-w-64 truncate px-4 py-2 text-muted" title={p.usage.last_error || ''}>
                  {p.usage.last_error ? `${p.usage.last_error} (${timeAgo(p.usage.last_error_at)})` : '—'}
                </td>
                <td className="px-4 py-2 tabular-nums">{p.track_count} ({p.playable_count})</td>
              </tr>
            ))}
          </Table>
        )}
      </section>

      <section className="max-w-xl rounded-lg bg-surface p-5">
        <h2 className="text-lg font-bold">Fetch a language now</h2>
        <p className="mt-1 text-sm text-muted">Pulls the next pages of popular tracks from every source that can filter by language. Respects each source&apos;s rate limit and daily quota.</p>
        <form onSubmit={sync} className="mt-4 flex flex-wrap items-end gap-3">
          <Field label="Language">
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className={`${inputClass} w-56`}>
              {languages.map((l) => <option key={l.code} value={l.code}>{l.name} ({l.native_name})</option>)}
            </select>
          </Field>
          <Field label="Pages">
            <input type="number" min={1} max={5} value={pages} onChange={(e) => setPages(Number(e.target.value))} className={`${inputClass} w-20`} />
          </Field>
          <Button type="submit" loading={syncing}>Fetch</Button>
        </form>
        {result && <ProviderStatusList providers={result.providers} className="mt-4" />}
      </section>

      {!loading && (
        <section>
          <h2 className="mb-3 text-xl font-bold">Sync progress</h2>
          <Table head={['Source', 'Language', 'Next offset', 'Imported', 'Last synced', 'Last error']}
            empty={data.every((p) => !p.sync.length) ? 'Nothing synced yet.' : null}>
            {data.flatMap((p) => p.sync.map((s) => (
              <tr key={`${p.key}-${s.language}`}>
                <td className="px-4 py-2">{p.name}</td>
                <td className="px-4 py-2">{s.language}{s.exhausted ? ' · done' : ''}</td>
                <td className="px-4 py-2 tabular-nums">{s.next_offset}</td>
                <td className="px-4 py-2 tabular-nums">{s.imported}</td>
                <td className="px-4 py-2 text-muted">{s.last_synced_at ? formatDate(s.last_synced_at) : '—'}</td>
                <td className="max-w-64 truncate px-4 py-2 text-muted">{s.last_error || '—'}</td>
              </tr>
            )))}
          </Table>
        </section>
      )}
    </div>
  )
}
