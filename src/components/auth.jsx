import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { AlertCircle, ChevronLeft, CircleCheck, Circle, Eye, EyeOff } from 'lucide-react'
import { authApi } from '../api/endpoints'
import { passwordRules } from '../lib/auth'
import { Spinner } from './ui'

/** Full-page auth layout: logo mark, big heading, one narrow column. */
export function AuthShell({ title, children, footer, wide = false }) {
  return (
    <div className="min-h-dvh bg-canvas px-4 pb-12 pt-10 sm:pt-16">
      <div className={`mx-auto ${wide ? 'max-w-md' : 'max-w-sm'}`}>
        <Link to="/" aria-label="Wavely home" className="mx-auto block w-fit">
          <img src="/favicon.svg" alt="" className="size-10" />
        </Link>
        {title && <h1 className="mt-6 text-center text-4xl font-black leading-tight tracking-tight sm:text-5xl">{title}</h1>}
        <div className="mt-8">{children}</div>
        {footer && <div className="mt-10 text-center">{footer}</div>}
      </div>
    </div>
  )
}

export const authInput = 'h-12 w-full rounded border border-zinc-500 bg-transparent px-3.5 text-base text-white placeholder:text-subtle hover:border-white focus:border-white focus:outline-none focus:ring-1 focus:ring-white aria-[invalid=true]:border-red-400'

export function AuthLabel({ htmlFor, children, hint }) {
  return (
    <label htmlFor={htmlFor} className="mb-2 block">
      <span className="text-sm font-bold">{children}</span>
      {hint && <span className="mt-0.5 block text-sm text-muted">{hint}</span>}
    </label>
  )
}

export function FieldError({ id, children }) {
  if (!children) return null
  return (
    <p id={id} role="alert" className="mt-2 flex items-start gap-1.5 text-sm text-red-300">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> <span>{children}</span>
    </p>
  )
}

export function Banner({ tone = 'error', children }) {
  if (!children) return null
  const tones = { error: 'bg-red-500/90 text-white', info: 'bg-sky-500/20 text-sky-100', success: 'bg-accent/20 text-accent' }
  return <div role={tone === 'error' ? 'alert' : 'status'} className={`mb-6 rounded px-4 py-3 text-sm font-semibold ${tones[tone]}`}>{children}</div>
}

export function PrimaryButton({ loading, children, className = '', ...props }) {
  return (
    <button {...props} disabled={props.disabled || loading}
      className={`flex h-12 w-full items-center justify-center gap-2 rounded-full bg-accent text-base font-bold text-black transition hover:scale-[1.02] hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100 ${className}`}>
      {loading && <Spinner className="size-4" />}
      {children}
    </button>
  )
}

export function OrDivider() {
  return <p className="my-6 text-center text-sm text-zinc-300">or</p>
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 48 48" className="size-6" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>
  )
}

/** "or" + one outlined pill per sign-in provider the server actually supports. */
export function SocialButtons({ verb = 'Continue' }) {
  const [google, setGoogle] = useState(false)
  useEffect(() => {
    authApi.providers().then((p) => setGoogle(p.google)).catch(() => {})
  }, [])
  if (!google) return null
  return (
    <>
      <OrDivider />
      <a href="/api/v1/auth/google/login"
        className="relative flex h-12 w-full items-center justify-center rounded-full border border-zinc-500 font-bold transition hover:border-white">
        <span className="absolute left-8"><GoogleIcon /></span>
        {verb} with Google
      </a>
    </>
  )
}

/** Progress bar + "Step n of N" + title, with a back chevron. */
export function StepHeader({ step, total, title, onBack }) {
  return (
    <div className="mb-8">
      <div className="h-0.5 w-full bg-zinc-600" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={step}
        aria-label={`Step ${step} of ${total}`}>
        <div className="h-full bg-accent transition-all" style={{ width: `${(step / total) * 100}%` }} />
      </div>
      <div className="mt-5 flex items-center gap-3">
        <button type="button" onClick={onBack} aria-label="Go back" className="rounded-full p-1 text-muted hover:text-white">
          <ChevronLeft className="size-7" />
        </button>
        <div>
          <p className="text-muted">Step {step} of {total}</p>
          <h2 className="font-bold">{title}</h2>
        </div>
      </div>
    </div>
  )
}

export function BackButton({ onClick }) {
  return (
    <button type="button" onClick={onClick} aria-label="Go back" className="-ml-1 mb-6 rounded-full p-1 text-muted hover:text-white">
      <ChevronLeft className="size-7" />
    </button>
  )
}

export function PasswordInput({ id, value, onChange, autoComplete = 'new-password', invalid, describedBy, autoFocus }) {
  const [shown, setShown] = useState(false)
  return (
    <div className="relative">
      <input id={id} type={shown ? 'text' : 'password'} value={value} onChange={onChange} autoComplete={autoComplete}
        autoFocus={autoFocus} aria-invalid={invalid || undefined} aria-describedby={describedBy} className={`${authInput} pr-12`} />
      <button type="button" onClick={() => setShown((s) => !s)} aria-label={shown ? 'Hide password' : 'Show password'}
        aria-pressed={shown} className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-muted hover:text-white">
        {shown ? <Eye className="size-5" /> : <EyeOff className="size-5" />}
      </button>
    </div>
  )
}

/** Live checklist under a new-password field; mirrors the server's rules. */
export function PasswordChecklist({ value, id }) {
  const rules = passwordRules(value)
  return (
    <div id={id} className="mt-5">
      <p className="text-sm font-bold">Your password must contain at least</p>
      <ul className="mt-2 space-y-1.5 text-sm">
        {rules.map((r) => (
          <li key={r.id} className={`flex items-center gap-2 ${r.ok ? 'text-white' : 'text-zinc-300'}`}>
            {r.ok ? <CircleCheck className="size-4 text-accent" aria-hidden="true" /> : <Circle className="size-4 text-zinc-500" aria-hidden="true" />}
            {r.label}<span className="sr-only">{r.ok ? ' (done)' : ' (missing)'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Six single-digit boxes: auto-advance, backspace to previous, and paste of the whole code. */
export function CodeInput({ value, onChange, length = 6, invalid, disabled }) {
  const refs = useRef([])
  const digits = Array.from({ length }, (_, i) => value[i] || '')
  useEffect(() => {
    refs.current[0]?.focus()
  }, [])

  const setAt = (index, char) => {
    const next = digits.slice()
    next[index] = char
    onChange(next.join('').slice(0, length))
  }
  const onInput = (index, raw) => {
    const clean = raw.replace(/\D/g, '')
    if (clean.length > 1) { // pasted or autofilled the whole code
      onChange(clean.slice(0, length))
      refs.current[Math.min(clean.length, length) - 1]?.focus()
      return
    }
    setAt(index, clean)
    if (clean && index < length - 1) refs.current[index + 1]?.focus()
  }
  const onKeyDown = (index, e) => {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      e.preventDefault()
      setAt(index - 1, '')
      refs.current[index - 1]?.focus()
    } else if (e.key === 'ArrowLeft' && index > 0) refs.current[index - 1]?.focus()
    else if (e.key === 'ArrowRight' && index < length - 1) refs.current[index + 1]?.focus()
  }

  return (
    <div className="flex justify-between gap-2" role="group" aria-label="Verification code">
      {digits.map((d, i) => (
        <input key={i} ref={(el) => { refs.current[i] = el }} value={d} inputMode="numeric" pattern="[0-9]*"
          autoComplete={i === 0 ? 'one-time-code' : 'off'} maxLength={i === 0 ? length : 1} disabled={disabled}
          aria-label={`Digit ${i + 1}`} aria-invalid={invalid || undefined}
          onChange={(e) => onInput(i, e.target.value)} onKeyDown={(e) => onKeyDown(i, e)} onFocus={(e) => e.target.select()}
          className="h-16 w-full min-w-0 rounded border border-zinc-500 bg-transparent text-center text-2xl font-bold focus:border-2 focus:border-white focus:outline-none aria-[invalid=true]:border-red-400" />
      ))}
    </div>
  )
}
