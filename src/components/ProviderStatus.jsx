const LABELS = {
  ok: null, disabled: 'disabled', not_configured: 'not configured', unsupported: 'can’t filter this',
  rate_limited: 'busy — try later', quota_exceeded: 'daily limit reached', timeout: 'slow to respond', error: 'unavailable',
}

/** One chip per provider: how many results it contributed, or why it didn't. */
export function ProviderStatusList({ providers, className = '' }) {
  if (!providers?.length) return null
  return (
    <ul className={`flex flex-wrap gap-2 text-xs ${className}`} aria-label="Sources searched">
      {providers.map((p) => {
        const ok = p.status === 'ok'
        return (
          <li key={p.key} title={p.message || undefined}
            className={`rounded-full px-2.5 py-1 ring-1 ${ok ? 'text-zinc-200 ring-zinc-600' : 'text-subtle ring-line'}`}>
            <span className="font-semibold">{p.name}</span>{' '}
            {ok ? <span className="text-muted">· {p.count}</span> : <span>· {LABELS[p.status] || p.status}</span>}
          </li>
        )
      })}
    </ul>
  )
}
