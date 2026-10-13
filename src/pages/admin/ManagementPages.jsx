import { useState } from 'react'
import { Link } from 'react-router'
import { RotateCcw, Trash2 } from 'lucide-react'
import { adminApi, playlistApi } from '../../api/endpoints'
import { Badge, Button, ErrorState, Modal, Spinner, inputClass } from '../../components/ui'
import { useAuth } from '../../context/AuthContext'
import { useToast } from '../../context/ToastContext'
import { useApi, useDebounce } from '../../hooks/useApi'
import { formatDate, formatMoney, timeAgo } from '../../lib/format'
import { Pagination, Table } from './AdminLayout'

function useMutation() {
  const toast = useToast()
  return async (fn, success) => {
    try {
      await fn()
      if (success) toast.success(success)
      return true
    } catch (err) {
      toast.apiError(err)
      return false
    }
  }
}

export function UsersAdmin() {
  const { user: me } = useAuth()
  const mutate = useMutation()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [page, setPage] = useState(1)
  const debounced = useDebounce(q, 300)
  const { data, error, loading, reload } = useApi(() => adminApi.users({ q: debounced, role, page, page_size: 20 }), [debounced, role, page])
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-3">
        <input value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Search by name or email" aria-label="Search users" className={`${inputClass} max-w-xs`} />
        <select value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }} aria-label="Filter by role" className={`${inputClass} w-auto`}>
          <option value="">All roles</option><option value="listener">Listener</option><option value="content_manager">Content manager</option><option value="admin">Admin</option>
        </select>
      </div>
      {loading ? <Spinner /> : (
        <>
          <Table head={['User', 'Role', 'Plan', 'Joined', 'Last login', 'Status', '']}>
            {data.items.map((u) => (
              <tr key={u.id} className="hover:bg-surface">
                <td className="px-4 py-2"><p className="font-medium">{u.display_name}</p><p className="text-xs text-muted">{u.email}</p></td>
                <td className="px-4 py-2">
                  <select value={u.role} disabled={u.id === me.id} aria-label={`Role for ${u.email}`} className="rounded bg-elevated px-2 py-1 text-sm"
                    onChange={async (e) => (await mutate(() => adminApi.updateUser(u.id, { role: e.target.value }), 'Role updated')) && reload({ silent: true })}>
                    <option value="listener">Listener</option><option value="content_manager">Content manager</option><option value="admin">Admin</option>
                  </select>
                </td>
                <td className="px-4 py-2">{u.is_premium ? <Badge tone="warn">premium</Badge> : (
                  <button className="text-xs text-muted underline hover:text-white"
                    onClick={async () => (await mutate(() => adminApi.grantPremium(u.id, 30), 'Granted 30 days of Premium')) && reload({ silent: true })}>Grant 30 days</button>)}</td>
                <td className="px-4 py-2 text-muted">{formatDate(u.created_at)}</td>
                <td className="px-4 py-2 text-muted">{u.last_login_at ? timeAgo(u.last_login_at) : 'never'}</td>
                <td className="px-4 py-2">
                  <button disabled={u.id === me.id} className="disabled:opacity-40"
                    onClick={async () => (await mutate(() => adminApi.updateUser(u.id, { is_active: !u.is_active }), u.is_active ? 'Account disabled' : 'Account enabled')) && reload({ silent: true })}>
                    {u.is_active ? <Badge tone="accent">active</Badge> : <Badge tone="danger">disabled</Badge>}
                  </button>
                </td>
                <td className="px-4 py-2 text-right">
                  {u.id !== me.id && (
                    <button aria-label={`Delete ${u.email}`} className="p-1 text-muted hover:text-danger"
                      onClick={async () => window.confirm(`Permanently delete ${u.email}?`) && (await mutate(() => adminApi.deleteUser(u.id), 'User deleted')) && reload()}><Trash2 className="size-4" /></button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pages={data.pages} total={data.total} onChange={setPage} />
        </>
      )}
    </>
  )
}

export function PlaylistsAdmin() {
  const mutate = useMutation()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const debounced = useDebounce(q, 300)
  const { data, error, loading, reload } = useApi(() => adminApi.playlists({ q: debounced, page, page_size: 20 }), [debounced, page])
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <>
      <input value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Search playlists" aria-label="Search playlists" className={`${inputClass} mb-4 max-w-xs`} />
      {loading ? <Spinner /> : (
        <>
          <Table head={['Playlist', 'Owner', 'Visibility', 'Tracks', 'Updated', '']}>
            {data.items.map((p) => (
              <tr key={p.id} className="hover:bg-surface">
                <td className="px-4 py-2 font-medium"><Link to={`/playlist/${p.id}`} className="hover:underline">{p.name}</Link></td>
                <td className="px-4 py-2 text-muted">{p.owner.display_name}</td>
                <td className="px-4 py-2">{p.is_collaborative ? <Badge tone="sky">collaborative</Badge> : p.is_public ? <Badge tone="accent">public</Badge> : <Badge>private</Badge>}</td>
                <td className="px-4 py-2 text-muted">{p.track_count}</td>
                <td className="px-4 py-2 text-muted">{timeAgo(p.updated_at)}</td>
                <td className="px-4 py-2 text-right">
                  <button aria-label={`Delete ${p.name}`} className="p-1 text-muted hover:text-danger"
                    onClick={async () => window.confirm(`Delete "${p.name}" by ${p.owner.display_name}?`) && (await mutate(() => playlistApi.remove(p.id), 'Playlist removed')) && reload()}><Trash2 className="size-4" /></button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pages={data.pages} total={data.total} onChange={setPage} />
        </>
      )}
    </>
  )
}

export function BillingAdmin() {
  const mutate = useMutation()
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const subs = useApi(() => adminApi.subscriptions({ status, page, page_size: 20 }), [status, page])
  const payments = useApi(() => adminApi.payments({ page_size: 20 }), [])
  if (subs.error) return <ErrorState error={subs.error} onRetry={subs.reload} />
  return (
    <div className="space-y-8">
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xl font-bold">Subscriptions</h2>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} aria-label="Filter by status" className={`${inputClass} w-auto`}>
            <option value="">All statuses</option>
            {['active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete'].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        {subs.loading ? <Spinner /> : (
          <>
            <Table head={['User', 'Plan', 'Status', 'Provider', 'Period end', '']} empty={!subs.data.items.length && 'No subscriptions.'}>
              {subs.data.items.map((s) => (
                <tr key={s.id} className="hover:bg-surface">
                  <td className="px-4 py-2">{s.user_email}</td>
                  <td className="px-4 py-2 text-muted">{s.plan.replace('premium_', '')}</td>
                  <td className="px-4 py-2"><Badge tone={['active', 'trialing'].includes(s.status) ? 'accent' : s.status === 'past_due' ? 'warn' : 'zinc'}>{s.status}</Badge>{s.cancel_at_period_end && <span className="ml-1 text-xs text-muted">(cancels)</span>}</td>
                  <td className="px-4 py-2 text-muted">{s.provider}</td>
                  <td className="px-4 py-2 text-muted">{formatDate(s.current_period_end)}</td>
                  <td className="px-4 py-2 text-right">
                    {s.provider === 'manual' && s.status === 'active' && (
                      <Button variant="ghost" className="px-3 py-1" onClick={async () => window.confirm('Revoke this complimentary Premium?') && (await mutate(() => adminApi.revokeSubscription(s.id), 'Revoked')) && subs.reload()}>Revoke</Button>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
            <Pagination page={page} pages={subs.data.pages} total={subs.data.total} onChange={setPage} />
          </>
        )}
      </section>
      <section>
        <h2 className="mb-3 text-xl font-bold">Recent payments</h2>
        {payments.loading ? <Spinner /> : (
          <Table head={['Date', 'User', 'Amount', 'Status', 'Provider reference']} empty={!payments.data?.items.length && 'No payments yet.'}>
            {payments.data?.items.map((p) => (
              <tr key={p.id} className="hover:bg-surface">
                <td className="px-4 py-2 text-muted">{formatDate(p.created_at)}</td>
                <td className="px-4 py-2">{p.user_email || '(deleted user)'}</td>
                <td className="px-4 py-2 tabular-nums">{formatMoney(p.amount_cents, p.currency)}</td>
                <td className="px-4 py-2"><Badge tone={p.status === 'succeeded' ? 'accent' : 'danger'}>{p.status}</Badge></td>
                <td className="px-4 py-2 font-mono text-xs text-muted">{p.provider}:{p.provider_payment_id}</td>
              </tr>
            ))}
          </Table>
        )}
      </section>
    </div>
  )
}

export function WebhooksAdmin() {
  const mutate = useMutation()
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState(null)
  const { data, error, loading, reload } = useApi(() => adminApi.webhooks({ status, page, page_size: 25 }), [status, page])
  const tone = { processed: 'accent', failed: 'danger', ignored: 'zinc', received: 'sky', processing: 'warn' }
  if (error) return <ErrorState error={error} onRetry={reload} />
  return (
    <>
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm text-muted">Events are stored before processing. Duplicate deliveries are ignored, and failures retry automatically with backoff.</p>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} aria-label="Filter by status" className={`${inputClass} w-auto`}>
          <option value="">All</option>{Object.keys(tone).map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      {loading ? <Spinner /> : (
        <>
          <Table head={['Received', 'Type', 'Event ID', 'Status', 'Attempts', 'Next retry', '']} empty={!data.items.length && 'No webhook events.'}>
            {data.items.map((e) => (
              <tr key={e.id} className="cursor-pointer hover:bg-surface" onClick={async () => setDetail(await adminApi.webhook(e.id))}>
                <td className="px-4 py-2 text-muted">{timeAgo(e.received_at)}</td>
                <td className="px-4 py-2 font-mono text-xs">{e.event_type}</td>
                <td className="px-4 py-2 font-mono text-xs text-muted">{e.event_id}</td>
                <td className="px-4 py-2"><Badge tone={tone[e.status]}>{e.status}</Badge></td>
                <td className="px-4 py-2 text-muted">{e.attempts}</td>
                <td className="px-4 py-2 text-muted">{e.next_retry_at ? new Date(e.next_retry_at).toLocaleString() : '—'}</td>
                <td className="px-4 py-2 text-right">
                  <button aria-label={`Retry ${e.event_id}`} title="Re-run processing" className="p-1 text-muted hover:text-white"
                    onClick={async (ev) => {
                      ev.stopPropagation()
                      if (await mutate(() => adminApi.retryWebhook(e.id), 'Event re-processed')) reload({ silent: true })
                    }}>
                    <RotateCcw className="size-4" /></button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={page} pages={data.pages} total={data.total} onChange={setPage} />
        </>
      )}
      <Modal wide open={Boolean(detail)} onClose={() => setDetail(null)} title={detail?.event_type || ''}>
        {detail && (
          <div className="space-y-3 text-sm">
            {detail.last_error && <p className="rounded bg-red-500/15 p-3 font-mono text-xs text-red-200">{detail.last_error}</p>}
            <pre className="max-h-96 overflow-auto rounded bg-canvas p-3 text-xs">{JSON.stringify(detail.payload, null, 2)}</pre>
          </div>
        )}
      </Modal>
    </>
  )
}
