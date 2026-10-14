import { useEffect, useRef } from 'react'
import { AlertTriangle, Loader2, Music2, X } from 'lucide-react'

const GRADIENTS = [
  'from-violet-600 to-indigo-900', 'from-rose-500 to-fuchsia-900', 'from-sky-500 to-blue-900',
  'from-amber-500 to-orange-900', 'from-emerald-500 to-teal-900', 'from-pink-500 to-purple-900',
]

function hash(str = '') {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0
  return Math.abs(h)
}

/** Artwork with a deterministic gradient fallback when there's no image. */
export function Cover({ src, alt = '', seed, className = '', rounded = 'rounded-md', icon: Icon = Music2 }) {
  if (src) {
    return <img src={src} alt={alt} loading="lazy" className={`aspect-square object-cover ${rounded} ${className}`} />
  }
  return (
    <div role="img" aria-label={alt}
      className={`flex aspect-square items-center justify-center bg-gradient-to-br ${GRADIENTS[hash(seed || alt) % GRADIENTS.length]} ${rounded} ${className}`}>
      <Icon className="size-1/3 text-white/80" />
    </div>
  )
}

export function Avatar({ user, size = 'size-8' }) {
  const initials = (user?.display_name || '?').split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()
  if (user?.avatar_url) return <img src={user.avatar_url} alt={user.display_name} className={`${size} rounded-full object-cover`} />
  return (
    <div title={user?.display_name} aria-label={user?.display_name}
      className={`${size} flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${GRADIENTS[hash(user?.id) % GRADIENTS.length]} text-xs font-bold`}>
      {initials}
    </div>
  )
}

export function Skeleton({ className = '' }) {
  return <div className={`skeleton rounded-md ${className}`} aria-hidden="true" />
}

export function CardGridSkeleton({ count = 6 }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-lg bg-surface p-3">
          <Skeleton className="aspect-square w-full" />
          <Skeleton className="mt-3 h-4 w-3/4" />
          <Skeleton className="mt-2 h-3 w-1/2" />
        </div>
      ))}
    </div>
  )
}

export function TrackListSkeleton({ rows = 6 }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-2 py-1.5">
          <Skeleton className="size-10" />
          <div className="flex-1 space-y-2"><Skeleton className="h-3.5 w-1/3" /><Skeleton className="h-3 w-1/5" /></div>
          <Skeleton className="h-3 w-10" />
        </div>
      ))}
    </div>
  )
}

export function PageSkeleton() {
  return (
    <div className="p-6">
      <div className="flex items-end gap-6">
        <Skeleton className="size-48 shrink-0" />
        <div className="flex-1 space-y-3"><Skeleton className="h-4 w-20" /><Skeleton className="h-12 w-2/3" /><Skeleton className="h-4 w-1/3" /></div>
      </div>
      <div className="mt-10"><TrackListSkeleton /></div>
    </div>
  )
}

export function Spinner({ className = 'size-5' }) {
  return <Loader2 className={`animate-spin ${className}`} aria-label="Loading" />
}

export function ErrorState({ error, onRetry, title = "Couldn't load this" }) {
  const notFound = error?.status === 404
  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center px-6 py-16 text-center">
      <AlertTriangle className="size-10 text-warn" />
      <h2 className="mt-4 text-xl font-bold">{notFound ? 'Not found' : title}</h2>
      <p className="mt-2 text-sm text-muted">{notFound ? "This page doesn't exist or you don't have access to it." : error?.message || 'Please try again.'}</p>
      {onRetry && !notFound && (
        <button onClick={() => onRetry()} className="mt-6 rounded-full bg-white px-5 py-2 text-sm font-bold text-black hover:scale-105">
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ icon: Icon = Music2, title, children, action }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <Icon className="size-12 text-subtle" />
      <h3 className="mt-4 text-lg font-bold">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-sm text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Button({ variant = 'primary', className = '', loading, children, ...props }) {
  const styles = {
    primary: 'bg-accent text-black hover:bg-accent-strong hover:scale-[1.03]',
    white: 'bg-white text-black hover:scale-[1.03]',
    outline: 'border border-zinc-500 text-white hover:border-white',
    ghost: 'text-muted hover:text-white hover:bg-hover',
    danger: 'bg-red-500/90 text-white hover:bg-red-500',
  }
  return (
    <button {...props} disabled={props.disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-full px-5 py-2 text-sm font-bold transition disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100 ${styles[variant]} ${className}`}>
      {loading && <Spinner className="size-4" />}
      {children}
    </button>
  )
}

export function Modal({ open, onClose, title, children, wide = false }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const previous = document.activeElement
    ref.current?.querySelector('input, textarea, select, button')?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={`max-h-[90vh] w-full overflow-y-auto rounded-xl bg-elevated p-6 shadow-2xl ${wide ? 'max-w-2xl' : 'max-w-md'}`}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-1 text-muted hover:bg-hover hover:text-white"><X className="size-5" /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Field({ label, error, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-subtle">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-danger">{error}</span>}
    </label>
  )
}

export const selectClass = 'w-auto rounded-md border border-line bg-surface px-3 py-2 text-sm text-white focus:border-white focus:outline-none'
export const inputClass = 'w-full rounded-md border border-line bg-surface px-3 py-2.5 text-sm text-white placeholder:text-subtle focus:border-white focus:outline-none'

export function SectionHeader({ title, to, linkLabel = 'Show all', LinkComponent }) {
  return (
    <div className="mb-4 flex items-end justify-between">
      <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
      {to && LinkComponent && <LinkComponent to={to} className="text-sm font-bold text-muted hover:underline">{linkLabel}</LinkComponent>}
    </div>
  )
}

export function Badge({ children, tone = 'zinc' }) {
  const tones = { zinc: 'bg-zinc-700 text-zinc-200', accent: 'bg-accent/15 text-accent', warn: 'bg-amber-400/15 text-amber-300',
    danger: 'bg-red-500/15 text-red-300', sky: 'bg-sky-500/15 text-sky-300' }
  return <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide ${tones[tone]}`}>{children}</span>
}

export function Equalizer() {
  return (
    <span className="flex h-3.5 items-end gap-[2px]" aria-label="Now playing">
      {[0, 0.2, 0.4].map((d) => <span key={d} className="eq-bar w-[3px] rounded-sm bg-accent" style={{ height: '100%', animationDelay: `${d}s` }} />)}
    </span>
  )
}
