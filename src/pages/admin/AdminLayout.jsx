import { NavLink, Navigate, Outlet } from 'react-router'
import { useAuth } from '../../context/AuthContext'

export const ADMIN_SECTIONS = [
  { to: '/admin', label: 'Dashboard', perm: 'analytics:view', end: true },
  { to: '/admin/catalog', label: 'Catalog', perm: 'catalog:write' },
  { to: '/admin/sources', label: 'Sources', perm: 'catalog:write' },
  { to: '/admin/users', label: 'Users', perm: 'users:manage' },
  { to: '/admin/playlists', label: 'Playlists', perm: 'playlists:moderate' },
  { to: '/admin/billing', label: 'Billing', perm: 'billing:manage' },
  { to: '/admin/webhooks', label: 'Webhooks', perm: 'webhooks:manage' },
]

export function RequirePermission({ perm, children }) {
  const { can } = useAuth()
  if (!can(perm)) {
    const first = ADMIN_SECTIONS.find((s) => can(s.perm))
    return first ? <Navigate to={first.to} replace /> : <Navigate to="/" replace />
  }
  return children
}

export default function AdminLayout() {
  const { can } = useAuth()
  const sections = ADMIN_SECTIONS.filter((s) => can(s.perm))
  if (!sections.length) return <Navigate to="/" replace />
  return (
    <div className="px-4 md:px-6">
      <h1 className="text-3xl font-extrabold">Admin</h1>
      <nav aria-label="Admin sections" className="mt-4 flex gap-1 overflow-x-auto border-b border-line">
        {sections.map((s) => (
          <NavLink key={s.to} to={s.to} end={s.end}
            className={({ isActive }) => `whitespace-nowrap border-b-2 px-4 py-2 text-sm font-semibold ${isActive ? 'border-accent text-white' : 'border-transparent text-muted hover:text-white'}`}>
            {s.label}
          </NavLink>
        ))}
      </nav>
      <div className="py-6"><Outlet /></div>
    </div>
  )
}

/** Shared admin table pieces. */
export function Table({ head, children, empty }) {
  return (
    <div className="overflow-x-auto rounded-lg ring-1 ring-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface text-xs uppercase tracking-wide text-subtle">
          <tr>{head.map((h) => <th key={h} scope="col" className="px-4 py-3 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
      {empty && <p className="p-6 text-center text-sm text-muted">{empty}</p>}
    </div>
  )
}

export function Pagination({ page, pages, total, onChange }) {
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted">
      <span>{total} total</span>
      <div className="flex items-center gap-2">
        <button disabled={page <= 1} onClick={() => onChange(page - 1)} className="rounded-full border border-line px-3 py-1 disabled:opacity-40">Previous</button>
        <span>{page} / {pages}</span>
        <button disabled={page >= pages} onClick={() => onChange(page + 1)} className="rounded-full border border-line px-3 py-1 disabled:opacity-40">Next</button>
      </div>
    </div>
  )
}
