import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { Check, Crown, FlaskConical } from 'lucide-react'
import { billingApi, meApi } from '../api/endpoints'
import { setAccessToken } from '../api/client'
import { Avatar, Badge, Button, ErrorState, Field, Spinner, inputClass } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { formatDate, formatMoney } from '../lib/format'

function Card({ title, children }) {
  return (
    <section className="rounded-xl bg-surface p-6">
      <h2 className="mb-4 text-lg font-bold">{title}</h2>
      {children}
    </section>
  )
}

function SubscriptionCard() {
  const toast = useToast()
  const { refreshUser } = useAuth()
  const { data, error, loading, setData } = useApi(() => billingApi.status(), [])
  const payments = useApi(() => billingApi.payments(), [])
  const [busy, setBusy] = useState(false)
  if (loading) return <Card title="Plan"><Spinner /></Card>
  if (error) return <Card title="Plan"><p className="text-sm text-danger">{error.message}</p></Card>
  const sub = data.subscription

  const act = async (fn) => {
    setBusy(true)
    try {
      setData(await fn())
      await refreshUser()
    } catch (err) {
      toast.apiError(err)
    } finally {
      setBusy(false)
    }
  }
  const portal = async () => {
    try {
      window.location.href = (await billingApi.portal()).url
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <Card title="Plan">
      {sub ? (
        <div className="space-y-3 text-sm">
          <p className="flex items-center gap-2 text-base font-bold"><Crown className="size-5 text-amber-300" /> Wavely Premium
            <Badge tone="accent">{sub.status}</Badge>{sub.provider === 'manual' && <Badge tone="sky">complimentary</Badge>}</p>
          <p className="text-muted">{sub.plan === 'premium_yearly' ? 'Billed yearly' : 'Billed monthly'}
            {sub.current_period_end && <> · {sub.cancel_at_period_end ? 'Ends' : 'Renews'} on {formatDate(sub.current_period_end)}</>}</p>
          <div className="flex flex-wrap gap-2 pt-2">
            {sub.provider !== 'manual' && (sub.cancel_at_period_end
              ? <Button variant="white" loading={busy} onClick={() => act(billingApi.resume)}>Keep Premium</Button>
              : <Button variant="outline" loading={busy} onClick={() => { if (window.confirm('Cancel at the end of this billing period?')) act(billingApi.cancel) }}>Cancel plan</Button>)}
            {data.provider === 'stripe' && <Button variant="ghost" onClick={portal}>Manage billing</Button>}
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-muted">You&apos;re on Wavely Free.</p>
          <Link to="/premium" className="rounded-full bg-white px-5 py-2 text-sm font-bold text-black hover:scale-105">Explore Premium</Link>
        </div>
      )}
      {payments.data?.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 text-sm font-bold">Payment history</h3>
          <ul className="divide-y divide-line text-sm">
            {payments.data.map((p) => (
              <li key={p.id} className="flex items-center justify-between py-2">
                <span>{formatDate(p.created_at)} · {p.description}</span>
                <span className={p.status === 'succeeded' ? '' : 'text-danger'}>{formatMoney(p.amount_cents, p.currency)} {p.status !== 'succeeded' && `(${p.status})`}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}

export function AccountPage() {
  const { user, setUser, logout, acceptSession } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [profile, setProfile] = useState({ display_name: user.display_name, email: user.email })
  const [pw, setPw] = useState({ current_password: '', new_password: '' })
  const [busy, setBusy] = useState(null)

  const saveProfile = async (e) => {
    e.preventDefault()
    setBusy('profile')
    try {
      setUser(await meApi.update(profile))
      toast.success('Profile saved')
    } catch (err) {
      toast.apiError(err)
    } finally {
      setBusy(null)
    }
  }
  const changePassword = async (e) => {
    e.preventDefault()
    setBusy('password')
    try {
      acceptSession(await meApi.changePassword(user.has_password ? pw : { new_password: pw.new_password }))
      setPw({ current_password: '', new_password: '' })
      toast.success('Password updated. Other devices have been signed out.')
    } catch (err) {
      toast.error(err.details?.[0]?.message?.replace(/^Value error, /, '') || err.message)
    } finally {
      setBusy(null)
    }
  }
  const uploadAvatar = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setBusy('avatar')
    try {
      setUser(await meApi.avatar(file))
      toast.success('Photo updated')
    } catch (err) {
      toast.apiError(err)
    } finally {
      setBusy(null)
    }
  }
  const deleteAccount = async () => {
    if (window.prompt('This permanently deletes your account, playlists and history. Type DELETE to confirm.') !== 'DELETE') return
    try {
      await meApi.remove()
      setAccessToken(null)
      await logout().catch(() => {})
      navigate('/register')
    } catch (err) {
      toast.apiError(err)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 md:px-6">
      <h1 className="text-3xl font-extrabold">Account</h1>
      <Card title="Profile">
        <div className="mb-6 flex items-center gap-4">
          <Avatar user={user} size="size-20" />
          <label className="cursor-pointer rounded-full border border-zinc-500 px-4 py-1.5 text-sm font-bold hover:border-white">
            {busy === 'avatar' ? 'Uploading…' : 'Change photo'}
            <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={uploadAvatar} />
          </label>
        </div>
        <form onSubmit={saveProfile} className="space-y-4">
          <Field label="Display name"><input required maxLength={80} className={inputClass} value={profile.display_name} onChange={(e) => setProfile({ ...profile, display_name: e.target.value })} /></Field>
          <Field label="Email"><input type="email" required className={inputClass} value={profile.email} onChange={(e) => setProfile({ ...profile, email: e.target.value })} /></Field>
          <Button type="submit" variant="white" loading={busy === 'profile'}>Save profile</Button>
        </form>
      </Card>
      <SubscriptionCard />
      <Card title={user.has_password ? 'Change password' : 'Set a password'}>
        <form onSubmit={changePassword} className="space-y-4">
          {user.has_password && <Field label="Current password"><input type="password" required autoComplete="current-password" className={inputClass} value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>}
          <Field label="New password" hint="At least 8 characters, mixing letters with numbers or symbols."><input type="password" required autoComplete="new-password" className={inputClass} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          <Button type="submit" variant="white" loading={busy === 'password'}>Update password</Button>
        </form>
      </Card>
      <Card title="Delete account">
        <p className="mb-4 text-sm text-muted">Permanently remove your account and everything in it.</p>
        <Button variant="danger" onClick={deleteAccount}>Delete account</Button>
      </Card>
    </div>
  )
}

export function PremiumPage() {
  const { user, refreshUser } = useAuth()
  const toast = useToast()
  const [params] = useSearchParams()
  const plans = useApi(() => billingApi.plans(), [])
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    if (params.get('checkout') === 'success') {
      const paymentId = params.get('razorpay_payment_id')
      const paymentLinkId = params.get('razorpay_payment_link_id')
      if (paymentId) {
        billingApi.verifyRazorpay({ payment_id: paymentId, payment_link_id: paymentLinkId })
          .then(() => {
            toast.success('UPI Payment successful! Premium is now active 🎉')
            refreshUser().catch(() => {})
          })
          .catch((err) => {
            toast.apiError(err)
            refreshUser().catch(() => {})
          })
      } else {
        toast.success('Payment received! Premium will be active in a moment')
        refreshUser().catch(() => {})
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const checkout = async (plan) => {
    setBusy(plan)
    try {
      window.location.href = (await billingApi.checkout(plan)).url // provider-hosted (or dev) checkout page
    } catch (err) {
      toast.apiError(err)
      setBusy(null)
    }
  }

  if (plans.error) return <ErrorState error={plans.error} onRetry={plans.reload} />
  return (
    <div className="px-4 md:px-6">
      <div className="-mt-16 bg-gradient-to-b from-amber-700/60 to-transparent px-2 pb-10 pt-28 text-center">
        <h1 className="text-4xl font-black md:text-5xl">{user.is_premium ? "You're on Premium" : 'Listen without limits'}</h1>
        <p className="mt-3 text-lg text-zinc-200">{user.is_premium ? 'Thanks for supporting Wavely.' : 'Premium-only releases, unlimited playlists and group sessions.'}</p>
      </div>
      {user.is_premium ? (
        <p className="text-center"><Link to="/account" className="font-bold underline">Manage your plan</Link></p>
      ) : plans.loading ? <Spinner /> : (
        <div className="mx-auto grid max-w-3xl gap-6 md:grid-cols-2">
          {plans.data.map((plan) => (
            <div key={plan.id} className="flex flex-col rounded-xl bg-surface p-6 ring-1 ring-line">
              {plan.interval === 'year' && <span className="mb-2 self-start rounded bg-accent px-2 py-0.5 text-xs font-bold text-black">Save 17%</span>}
              <h2 className="text-2xl font-bold">{plan.name}</h2>
              <p className="mt-1 text-lg">{formatMoney(plan.amount_cents, plan.currency)} <span className="text-sm text-muted">/ {plan.interval}</span></p>
              <ul className="my-6 flex-1 space-y-2 text-sm">
                {plan.features.map((f) => <li key={f} className="flex gap-2"><Check className="size-4 shrink-0 text-accent" /> {f}</li>)}
              </ul>
              <Button loading={busy === plan.id} disabled={Boolean(busy)} onClick={() => checkout(plan.id)} className="py-3">Get {plan.name}</Button>
            </div>
          ))}
        </div>
      )}
      <p className="mx-auto mt-8 max-w-xl text-center text-xs text-subtle">Secure payments powered by Razorpay. Supports UPI (Google Pay, PhonePe, Paytm, QR code, BHIM), Cards, and Netbanking. Cancel any time.</p>
    </div>
  )
}

/** Only reachable with BILLING_PROVIDER=dev. No money moves; the backend emits signed test webhooks. */
export function DevCheckoutPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { refreshUser } = useAuth()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const complete = async () => {
    setBusy(true)
    try {
      await billingApi.devComplete(params.get('session') || '')
      await refreshUser()
      toast.success('Welcome to Premium!')
      navigate('/account')
    } catch (err) {
      toast.apiError(err)
      setBusy(false)
    }
  }
  return (
    <div className="mx-auto max-w-md px-4 py-10">
      <div className="rounded-xl bg-surface p-8 text-center ring-1 ring-amber-400/40">
        <FlaskConical className="mx-auto size-10 text-amber-300" />
        <h1 className="mt-4 text-2xl font-bold">Development checkout</h1>
        <p className="mt-2 text-sm text-muted">The server is running with <code className="text-white">BILLING_PROVIDER=dev</code>. No card is charged.
          Confirming sends signed test events through the real webhook pipeline, exactly as Stripe would.</p>
        <div className="mt-6 flex justify-center gap-3">
          <Button variant="ghost" onClick={() => navigate('/premium?checkout=cancelled')}>Cancel</Button>
          <Button loading={busy} onClick={complete}>Complete test payment</Button>
        </div>
      </div>
    </div>
  )
}
