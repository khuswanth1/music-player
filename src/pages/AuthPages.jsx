import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'
import { authApi } from '../api/endpoints'
import {
  AuthLabel, AuthShell, BackButton, Banner, CodeInput, FieldError, PasswordChecklist, PasswordInput, PrimaryButton,
  SocialButtons, StepHeader, authInput,
} from '../components/auth'
import { Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { EMAIL_RE, GENDERS, SIGNUP_FIELD_STEP, checkBirthDate, maskEmail, passwordValid } from '../lib/auth'

const TERMS_URL = import.meta.env.VITE_TERMS_URL
const PRIVACY_URL = import.meta.env.VITE_PRIVACY_URL
const MONTHS = Array.from({ length: 12 }, (_, i) => new Date(2000, i, 1).toLocaleString(undefined, { month: 'long' }))

function safeNext(params) {
  const next = params.get('next') || '/'
  return next.startsWith('/') && !next.startsWith('//') ? next : '/' // never redirect off-site
}

function fieldErrors(err) {
  const out = {}
  for (const d of err?.details || []) if (d.field) out[d.field] = d.message.replace(/^Value error, /, '')
  return out
}

function emailError(email) {
  if (!email.trim()) return 'Please enter your email address.'
  if (!EMAIL_RE.test(email.trim())) return 'This email is invalid. Make sure it’s written like example@email.com'
  return null
}

function rateLimited(err) {
  return err.status === 429 ? 'Too many attempts. Please wait a minute and try again.' : null
}

// --- log in: email → one-time code (or password) ---------------------------------------------------

export function LoginPage() {
  const { login, loginWithCode, status } = useAuth()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [stage, setStage] = useState('email') // email | code | password
  const [email, setEmail] = useState(params.get('email') || '')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (cooldown <= 0) return undefined
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  if (status === 'authenticated') return <Navigate to={safeNext(params)} replace />
  const done = () => navigate(safeNext(params), { replace: true })
  const go = (next) => {
    setError(null)
    setStage(next)
  }

  const sendCode = async () => {
    setBusy(true)
    setError(null)
    try {
      await authApi.loginCode(email.trim())
      setCode('')
      setCooldown(30)
      setStage('code')
    } catch (err) {
      setError(rateLimited(err) || err.message)
    } finally {
      setBusy(false)
    }
  }

  const submitEmail = (e) => {
    e.preventDefault()
    const problem = emailError(email)
    if (problem) return setError(problem)
    sendCode()
  }

  const submitCode = async (value = code) => {
    if (value.length !== 6 || busy) return
    setBusy(true)
    setError(null)
    try {
      await loginWithCode(email.trim(), value)
      done()
    } catch (err) {
      setError(rateLimited(err) || 'That code is wrong or has expired. Check your email or resend the code.')
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  const submitPassword = async (e) => {
    e.preventDefault()
    if (!password) return setError('Please enter your password.')
    setBusy(true)
    setError(null)
    try {
      await login(email.trim(), password)
      done()
    } catch (err) {
      setError(rateLimited(err) || 'Incorrect email or password.')
    } finally {
      setBusy(false)
    }
  }

  const signupLink = (
    <>
      <p className="text-muted">Don&apos;t have an account?</p>
      <Link to={`/register?${new URLSearchParams({ next: safeNext(params) })}`} className="mt-3 inline-block font-bold hover:text-accent hover:underline">Sign up</Link>
    </>
  )

  if (stage === 'code') {
    return (
      <AuthShell footer={signupLink}>
        <BackButton onClick={() => go('email')} />
        <h1 className="text-3xl font-black leading-tight tracking-tight">Enter the code we sent to {maskEmail(email)}</h1>
        <p className="mt-2 text-sm text-muted">It expires in 10 minutes. If no account uses this email, no code is sent.</p>
        <form onSubmit={(e) => { e.preventDefault(); submitCode() }} className="mt-8">
          <CodeInput value={code} invalid={Boolean(error)} disabled={busy}
            onChange={(v) => { setCode(v); setError(null); if (v.length === 6) submitCode(v) }} />
          <FieldError>{error}</FieldError>
          <div className="mt-6 flex justify-center">
            <button type="button" onClick={sendCode} disabled={cooldown > 0 || busy}
              className="rounded-full border border-zinc-500 px-5 py-2 text-sm font-bold hover:border-white disabled:cursor-not-allowed disabled:opacity-50">
              {cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}
            </button>
          </div>
          <PrimaryButton type="submit" loading={busy} disabled={code.length !== 6} className="mt-10">Next</PrimaryButton>
        </form>
        <button type="button" onClick={() => go('password')} className="mx-auto mt-8 block font-bold hover:underline">Log in with a password</button>
      </AuthShell>
    )
  }

  if (stage === 'password') {
    return (
      <AuthShell footer={signupLink}>
        <BackButton onClick={() => go('email')} />
        <h1 className="text-3xl font-black tracking-tight">Log in with a password</h1>
        <form onSubmit={submitPassword} className="mt-8 space-y-6" noValidate>
          <div>
            <AuthLabel htmlFor="login-email">Email</AuthLabel>
            <input id="login-email" type="email" autoComplete="username" className={authInput} value={email}
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <AuthLabel htmlFor="login-password">Password</AuthLabel>
            <PasswordInput id="login-password" value={password} autoComplete="current-password" autoFocus invalid={Boolean(error)}
              describedBy={error ? 'login-error' : undefined} onChange={(e) => { setPassword(e.target.value); setError(null) }} />
            <FieldError id="login-error">{error}</FieldError>
          </div>
          <PrimaryButton type="submit" loading={busy}>Log in</PrimaryButton>
        </form>
        <div className="mt-8 space-y-4 text-center">
          <button type="button" onClick={() => (EMAIL_RE.test(email.trim()) ? sendCode() : go('email'))} className="font-bold hover:underline">
            Log in without password
          </button>
          <Link to="/forgot-password" className="block text-sm text-muted underline hover:text-white">Forgot your password?</Link>
        </div>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Welcome back" footer={signupLink}>
      {params.get('reset') && <Banner tone="success">Password updated. Log in with your new password.</Banner>}
      {params.get('oauth_error') && <Banner>{OAUTH_ERRORS[params.get('oauth_error')] || 'Google sign-in didn’t complete. Please try again.'}</Banner>}
      <form onSubmit={submitEmail} noValidate>
        <AuthLabel htmlFor="login-email">Email</AuthLabel>
        <input id="login-email" type="email" autoComplete="email" autoFocus className={authInput} value={email}
          aria-invalid={Boolean(error) || undefined} aria-describedby={error ? 'email-error' : undefined}
          onChange={(e) => { setEmail(e.target.value); setError(null); if (params.get('reset')) setParams({}, { replace: true }) }} />
        <FieldError id="email-error">{error}</FieldError>
        <PrimaryButton type="submit" loading={busy} className="mt-6">Continue</PrimaryButton>
      </form>
      <SocialButtons verb="Continue" />
      <button type="button" onClick={() => { const p = emailError(email); if (p) setError(p); else go('password') }}
        className="mx-auto mt-6 block text-sm font-bold text-muted hover:text-white hover:underline">
        Log in with a password instead
      </button>
    </AuthShell>
  )
}

// --- sign up: email → password → about you → terms ----------------------------------------------

export function RegisterPage() {
  const { register, status } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [form, setForm] = useState({
    email: params.get('email') || '', password: '', display_name: '', year: '', month: '', day: '', gender: '',
    marketing_opt_out: false,
  })
  const [errors, setErrors] = useState({})
  const [banner, setBanner] = useState(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') return <Navigate to={safeNext(params)} replace />
  const set = (key, value) => {
    setForm((f) => ({ ...f, [key]: value }))
    setErrors((e) => ({ ...e, [key]: undefined, dob: key === 'year' || key === 'month' || key === 'day' ? undefined : e.dob }))
  }
  const back = () => {
    setBanner(null)
    setStep((s) => s - 1)
  }
  const loginLink = `/login?${new URLSearchParams({ next: safeNext(params) })}`

  const nextFromEmail = (e) => {
    e.preventDefault()
    const problem = emailError(form.email)
    if (problem) return setErrors({ email: problem })
    setBanner(null)
    setStep(1)
  }
  const nextFromPassword = (e) => {
    e.preventDefault()
    if (passwordValid(form.password)) setStep(2)
  }
  const nextFromProfile = (e) => {
    e.preventDefault()
    const out = {}
    if (!form.display_name.trim()) out.display_name = 'Enter a name for your profile.'
    const dob = checkBirthDate(form)
    if (dob.error) out.dob = dob.error
    if (!form.gender) out.gender = 'Select your gender.'
    setErrors(out)
    if (!Object.keys(out).length) setStep(3)
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setBanner(null)
    try {
      await register({
        email: form.email.trim(), password: form.password, display_name: form.display_name.trim(),
        date_of_birth: checkBirthDate(form).date, gender: form.gender, marketing_emails: !form.marketing_opt_out,
      })
      navigate(safeNext(params), { replace: true })
    } catch (err) {
      if (err.code === 'email_taken') {
        setStep(0)
        setErrors({ email: 'taken' })
        return
      }
      const fields = fieldErrors(err)
      const first = Object.keys(fields).sort((a, b) => (SIGNUP_FIELD_STEP[a] ?? 3) - (SIGNUP_FIELD_STEP[b] ?? 3))[0]
      if (first) {
        setStep(SIGNUP_FIELD_STEP[first] ?? 3)
        setErrors({ ...fields, dob: fields.date_of_birth })
      } else {
        setBanner(rateLimited(err) || err.message)
      }
    } finally {
      setBusy(false)
    }
  }

  if (step === 0) {
    return (
      <AuthShell title={<>Sign up to<br />start listening</>}
        footer={<><p className="text-muted">Already have an account?</p><Link to={loginLink} className="mt-3 inline-block font-bold hover:text-accent hover:underline">Log in here</Link></>}>
        <Banner>{banner}</Banner>
        <form onSubmit={nextFromEmail} noValidate>
          <AuthLabel htmlFor="signup-email">Email address</AuthLabel>
          <input id="signup-email" type="email" autoComplete="email" autoFocus placeholder="name@domain.com" className={authInput}
            value={form.email} onChange={(e) => set('email', e.target.value)} aria-invalid={Boolean(errors.email) || undefined}
            aria-describedby={errors.email ? 'signup-email-error' : undefined} />
          <FieldError id="signup-email-error">
            {errors.email === 'taken'
              ? <>This address is already linked to an existing account. To continue, <Link to={`${loginLink}&email=${encodeURIComponent(form.email.trim())}`} className="font-bold underline">log in</Link>.</>
              : errors.email}
          </FieldError>
          <PrimaryButton type="submit" className="mt-6">Next</PrimaryButton>
        </form>
        <SocialButtons verb="Sign up" />
      </AuthShell>
    )
  }

  return (
    <AuthShell wide>
      {step === 1 && (
        <form onSubmit={nextFromPassword} noValidate>
          <StepHeader step={1} total={3} title="Create a password" onBack={back} />
          <div className="px-1 sm:px-12">
            <AuthLabel htmlFor="signup-password">Password</AuthLabel>
            <PasswordInput id="signup-password" value={form.password} autoFocus describedBy="password-rules"
              invalid={Boolean(errors.password)} onChange={(e) => set('password', e.target.value)} />
            <FieldError>{errors.password}</FieldError>
            <PasswordChecklist id="password-rules" value={form.password} />
            <PrimaryButton type="submit" disabled={!passwordValid(form.password)} className="mt-10">Next</PrimaryButton>
          </div>
        </form>
      )}

      {step === 2 && (
        <form onSubmit={nextFromProfile} noValidate>
          <StepHeader step={2} total={3} title="Tell us about yourself" onBack={back} />
          <div className="space-y-7 px-1 sm:px-12">
            <div>
              <AuthLabel htmlFor="signup-name" hint="This name will appear on your profile">Name</AuthLabel>
              <input id="signup-name" autoComplete="nickname" maxLength={80} autoFocus className={authInput} value={form.display_name}
                onChange={(e) => set('display_name', e.target.value)} aria-invalid={Boolean(errors.display_name) || undefined} />
              <FieldError>{errors.display_name}</FieldError>
            </div>
            <fieldset>
              <legend className="mb-2">
                <span className="text-sm font-bold">Date of birth</span>
                <span className="mt-0.5 block text-sm text-muted">You must be at least 13 to use Wavely.</span>
              </legend>
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_minmax(0,0.9fr)] gap-2">
                <input aria-label="Year" placeholder="yyyy" inputMode="numeric" maxLength={4} autoComplete="bday-year" className={authInput}
                  value={form.year} onChange={(e) => set('year', e.target.value.replace(/\D/g, ''))} aria-invalid={Boolean(errors.dob) || undefined} />
                <select aria-label="Month" autoComplete="bday-month" className={`${authInput} ${form.month ? '' : 'text-subtle'}`}
                  value={form.month} onChange={(e) => set('month', e.target.value)} aria-invalid={Boolean(errors.dob) || undefined}>
                  <option value="">Month</option>
                  {MONTHS.map((m, i) => <option key={m} value={i + 1} className="text-white">{m}</option>)}
                </select>
                <input aria-label="Day" placeholder="dd" inputMode="numeric" maxLength={2} autoComplete="bday-day" className={authInput}
                  value={form.day} onChange={(e) => set('day', e.target.value.replace(/\D/g, ''))} aria-invalid={Boolean(errors.dob) || undefined} />
              </div>
              <FieldError>{errors.dob}</FieldError>
            </fieldset>
            <fieldset>
              <legend className="mb-3">
                <span className="text-sm font-bold">Gender</span>
                <span className="mt-0.5 block text-sm text-muted">Stored with your account and never shared.</span>
              </legend>
              <div className="flex flex-wrap gap-x-6 gap-y-3">
                {GENDERS.map((g) => (
                  <label key={g.id} className="flex cursor-pointer items-center gap-2.5">
                    <input type="radio" name="gender" value={g.id} checked={form.gender === g.id} onChange={() => set('gender', g.id)}
                      className="size-5 cursor-pointer accent-[var(--color-accent)]" />
                    {g.label}
                  </label>
                ))}
              </div>
              <FieldError>{errors.gender}</FieldError>
            </fieldset>
            <PrimaryButton type="submit">Next</PrimaryButton>
          </div>
        </form>
      )}

      {step === 3 && (
        <form onSubmit={submit} noValidate>
          <StepHeader step={3} total={3} title="Terms & Conditions" onBack={back} />
          <div className="space-y-4 px-1 sm:px-12">
            <Banner>{banner}</Banner>
            <label className="flex cursor-pointer gap-3 rounded-md bg-elevated p-4">
              <input type="checkbox" checked={form.marketing_opt_out} onChange={(e) => set('marketing_opt_out', e.target.checked)}
                className="mt-1 size-5 shrink-0 cursor-pointer accent-[var(--color-accent)]" />
              <span>I would prefer not to receive marketing emails from Wavely.</span>
            </label>
            <p className="pt-2 text-sm text-zinc-300">Wavely personalises your home screen and recommendations from what you play and like.</p>
            {TERMS_URL && (
              <p className="text-sm text-zinc-300">By clicking on sign-up, you agree to Wavely&apos;s <a href={TERMS_URL} target="_blank" rel="noopener noreferrer" className="text-accent underline">Terms and Conditions of Use</a>.</p>
            )}
            {PRIVACY_URL && (
              <p className="text-sm text-zinc-300">By clicking on sign-up, you confirm that you have read how we process your personal data in our <a href={PRIVACY_URL} target="_blank" rel="noopener noreferrer" className="text-accent underline">Privacy Policy</a>.</p>
            )}
            <PrimaryButton type="submit" loading={busy} className="!mt-10">Sign up</PrimaryButton>
          </div>
        </form>
      )}
    </AuthShell>
  )
}

// --- password reset ----------------------------------------------------------------------------

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    const problem = emailError(email)
    if (problem) return setError(problem)
    setBusy(true)
    setError(null)
    try {
      await authApi.forgot(email.trim())
      setSent(true)
    } catch (err) {
      setError(rateLimited(err) || err.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <AuthShell title="Reset your password" footer={<Link to="/login" className="font-bold hover:underline">Back to log in</Link>}>
      {sent ? (
        <p role="status" className="text-center text-zinc-300">
          If an account exists for {email.trim()}, we&apos;ve sent it a link to reset your password.
          {import.meta.env.DEV && <span className="mt-2 block text-sm text-subtle">In development, the link is printed in the backend log.</span>}
        </p>
      ) : (
        <form onSubmit={submit} noValidate>
          <p className="mb-6 text-center text-sm text-zinc-300">Enter your email and we&apos;ll send you a link to get back into your account.</p>
          <AuthLabel htmlFor="forgot-email">Email address</AuthLabel>
          <input id="forgot-email" type="email" autoComplete="email" autoFocus className={authInput} value={email}
            onChange={(e) => { setEmail(e.target.value); setError(null) }} aria-invalid={Boolean(error) || undefined} />
          <FieldError>{error}</FieldError>
          <PrimaryButton type="submit" loading={busy} className="mt-6">Send link</PrimaryButton>
        </form>
      )}
    </AuthShell>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    if (!passwordValid(password)) return
    setBusy(true)
    setError(null)
    try {
      await authApi.reset(token, password)
      navigate('/login?reset=1', { replace: true })
    } catch (err) {
      setError(fieldErrors(err).new_password || err.message)
    } finally {
      setBusy(false)
    }
  }
  if (!token) {
    return <AuthShell title="Invalid link"><p className="text-center text-zinc-300">This reset link is missing its token. <Link to="/forgot-password" className="underline">Request a new one</Link>.</p></AuthShell>
  }
  return (
    <AuthShell title="Choose a new password">
      <form onSubmit={submit} noValidate>
        <Banner>{error}</Banner>
        <AuthLabel htmlFor="reset-password">New password</AuthLabel>
        <PasswordInput id="reset-password" value={password} autoFocus describedBy="reset-rules" onChange={(e) => setPassword(e.target.value)} />
        <PasswordChecklist id="reset-rules" value={password} />
        <PrimaryButton type="submit" loading={busy} disabled={!passwordValid(password)} className="mt-10">Update password</PrimaryButton>
      </form>
    </AuthShell>
  )
}

/** Google OAuth lands here; the refresh cookie is already set, so exchange it for an access token. */
const OAUTH_ERRORS = {
  oauth_cancelled: 'Google sign-in was cancelled.',
  oauth_misconfigured: 'Google sign-in isn’t available right now. Log in with your email instead.',
  oauth_email_unverified: 'Your Google account’s email address isn’t verified.',
  oauth_state_invalid: 'That Google sign-in link expired. Please try again.',
  account_disabled: 'This account has been disabled.',
}

/** Google OAuth lands here. Success goes straight to the app; any failure returns to the login page. */
export function AuthCallbackPage() {
  const { resume } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const error = params.get('error')
  useEffect(() => {
    if (error) {
      navigate(`/login?${new URLSearchParams({ oauth_error: error })}`, { replace: true })
      return
    }
    // The backend set the httpOnly refresh cookie before redirecting here; trade it for an access token.
    resume()
      .then(() => navigate('/', { replace: true }))
      .catch(() => navigate(`/login?${new URLSearchParams({ oauth_error: 'oauth_failed' })}`, { replace: true }))
  }, [error, resume, navigate])
  return <div className="flex h-dvh items-center justify-center bg-canvas"><Spinner className="size-8 text-accent" /></div>
}
