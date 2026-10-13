import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const idRef = useRef(0)

  const dismiss = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), [])

  const push = useCallback((message, { type = 'info', action, duration = 4000 } = {}) => {
    const id = ++idRef.current
    setToasts((t) => [...t.slice(-3), { id, message, type, action }])
    if (duration) setTimeout(() => dismiss(id), duration)
    return id
  }, [dismiss])

  const api = useMemo(() => ({
    push,
    success: (m, o) => push(m, { ...o, type: 'success' }),
    error: (m, o) => push(m, { ...o, type: 'error', duration: 6000 }),
    info: (m, o) => push(m, { ...o, type: 'info' }),
    /** Shows an API error; premium errors get an upgrade link. */
    apiError: (err, fallback = 'Something went wrong') => {
      if (err?.code === 'premium_required') {
        return push(err.message, { type: 'info', duration: 7000, action: { to: '/premium', label: 'Get Premium' } })
      }
      return push(err?.message || fallback, { type: 'error', duration: 6000 })
    },
  }), [push])

  const icons = { success: CheckCircle2, error: AlertCircle, info: Info }
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-28 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-28" aria-live="polite">
        {toasts.map((t) => {
          const Icon = icons[t.type]
          return (
            <div key={t.id} role={t.type === 'error' ? 'alert' : 'status'}
              className="pointer-events-auto flex max-w-md items-center gap-3 rounded-lg bg-white px-4 py-3 text-sm font-medium text-zinc-900 shadow-2xl">
              <Icon className={`size-5 shrink-0 ${t.type === 'error' ? 'text-red-600' : t.type === 'success' ? 'text-emerald-600' : 'text-sky-600'}`} />
              <span className="flex-1">{t.message}</span>
              {t.action && (
                <Link to={t.action.to} onClick={() => dismiss(t.id)} className="shrink-0 font-bold text-emerald-700 hover:underline">
                  {t.action.label}
                </Link>
              )}
              <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-zinc-500 hover:text-zinc-900">
                <X className="size-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
