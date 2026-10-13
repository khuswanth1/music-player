import { useState } from 'react'
import { Link } from 'react-router'
import { Copy, Crown, ListPlus, LogOut, Pause, Play, Search, SkipForward, Users, X } from 'lucide-react'
import { catalogApi } from '../api/endpoints'
import { Avatar, Button, Cover, EmptyState, Field, inputClass, Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { usePlayer } from '../context/PlayerContext'
import { useSession } from '../context/SessionContext'
import { useToast } from '../context/ToastContext'
import { useApi, useDebounce } from '../hooks/useApi'
import { formatDuration } from '../lib/format'
import { songCover } from '../lib/tracks'

function StartOrJoin() {
  const { user } = useAuth()
  const { start, join } = useSession()
  const toast = useToast()
  const [name, setName] = useState(`${user.display_name.split(' ')[0]}'s session`)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(null)
  const run = async (kind, fn) => {
    setBusy(kind)
    try {
      await fn()
    } catch (err) {
      toast.apiError(err)
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="mx-auto grid max-w-4xl gap-6 px-4 md:grid-cols-2 md:px-6">
      <div className="md:col-span-2">
        <h1 className="text-3xl font-extrabold">Listen together</h1>
        <p className="mt-1 text-muted">Start a group session and everyone hears the same thing at the same time. Guests can add songs to a shared queue.</p>
      </div>
      <form className="rounded-xl bg-surface p-6" onSubmit={(e) => { e.preventDefault(); run('start', () => start(name)) }}>
        <h2 className="mb-4 flex items-center gap-2 text-lg font-bold">Host a session {!user.is_premium && <Crown className="size-4 text-amber-300" aria-label="Premium" />}</h2>
        <Field label="Session name"><input className={inputClass} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        {user.is_premium ? <Button type="submit" loading={busy === 'start'} className="mt-4">Start session</Button>
          : <p className="mt-4 text-sm text-muted">Hosting is a Premium feature. <Link to="/premium" className="font-bold text-white underline">Upgrade</Link> — or join a friend&apos;s session for free.</p>}
      </form>
      <form className="rounded-xl bg-surface p-6" onSubmit={(e) => { e.preventDefault(); run('join', () => join(code.trim())) }}>
        <h2 className="mb-4 text-lg font-bold">Join with a code</h2>
        <Field label="Invite code"><input required className={inputClass} value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. Xk3_b9Qa" /></Field>
        <Button type="submit" variant="white" loading={busy === 'join'} className="mt-4">Join</Button>
      </form>
    </div>
  )
}

function AddToSession() {
  const { control } = useSession()
  const [q, setQ] = useState('')
  const debounced = useDebounce(q.trim(), 250)
  const { data, loading } = useApi((signal) => debounced ? catalogApi.search({ q: debounced, type: 'song', page_size: 6 }, signal) : Promise.resolve(null), [debounced])
  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a song to add" aria-label="Search songs to add to the session" className={`${inputClass} pl-9`} />
      </div>
      {loading && debounced && <Spinner className="mt-3" />}
      <ul className="mt-2">
        {data?.songs?.items.map((s) => (
          <li key={s.id} className="flex items-center gap-3 rounded-md p-2 hover:bg-hover">
            <Cover src={songCover(s)} seed={s.album?.id} alt="" className="size-9" rounded="rounded" />
            <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{s.title}</p><p className="truncate text-xs text-muted">{s.artist.name}</p></div>
            <button onClick={() => { control('queue_add', { song_id: s.id }); setQ('') }} aria-label={`Add ${s.title} to the shared queue`} className="text-muted hover:text-white"><ListPlus className="size-5" /></button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function SessionsPage() {
  const { active, presence, isHost, control, leave } = useSession()
  const { position } = usePlayer()
  const toast = useToast()
  if (!active) return <StartOrJoin />
  const song = active.current_song
  const online = new Set(presence.map((u) => u.user_id))
  const copy = () => navigator.clipboard.writeText(active.invite_code).then(() => toast.success('Invite code copied'), () => toast.info(active.invite_code))

  return (
    <div className="mx-auto max-w-5xl px-4 md:px-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold text-accent"><Users className="size-4" /> Group session · {isHost ? 'you are the host' : `hosted by ${active.host.display_name}`}</p>
          <h1 className="text-4xl font-black">{active.name}</h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={copy}><Copy className="size-4" /> Code: <span className="font-mono">{active.invite_code}</span></Button>
          <Button variant={isHost ? 'danger' : 'ghost'} onClick={leave}><LogOut className="size-4" /> {isHost ? 'End session' : 'Leave'}</Button>
        </div>
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section className="rounded-xl bg-surface p-6">
          {song ? (
            <div className="flex flex-col items-center gap-6 sm:flex-row">
              <Cover src={songCover(song)} seed={song.album?.id} alt="" className="size-48 shadow-2xl" />
              <div className="min-w-0 flex-1 text-center sm:text-left">
                <p className="text-sm text-muted">{active.is_playing ? 'Now playing' : 'Paused'}</p>
                <h2 className="truncate text-3xl font-bold">{song.title}</h2>
                <p className="text-muted">{song.artist.name}</p>
                <p className="mt-2 text-sm tabular-nums text-muted">{formatDuration(position)} / {formatDuration(song.duration_ms)}</p>
                {isHost && (
                  <div className="mt-4 flex justify-center gap-3 sm:justify-start">
                    <button onClick={() => control(active.is_playing ? 'pause' : 'play')} aria-label={active.is_playing ? 'Pause for everyone' : 'Play for everyone'}
                      className="flex size-12 items-center justify-center rounded-full bg-white text-black hover:scale-105">
                      {active.is_playing ? <Pause className="size-5" fill="currentColor" /> : <Play className="ml-0.5 size-5" fill="currentColor" />}
                    </button>
                    <button onClick={() => control('next')} aria-label="Next song for everyone" className="flex size-12 items-center justify-center rounded-full bg-elevated hover:bg-hover"><SkipForward className="size-5" /></button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <EmptyState title="Nothing playing yet"
              action={isHost && active.queue.length > 0 && <Button onClick={() => control('next')}><Play className="size-4" fill="currentColor" /> Start the queue</Button>}>
              {isHost ? 'Play any song from the app, or add songs to the shared queue and start it.' : 'Waiting for the host to pick a song.'}
            </EmptyState>
          )}
          <h3 className="mb-2 mt-8 font-bold">Up next</h3>
          {active.queue.length === 0 && <p className="text-sm text-muted">The shared queue is empty — anyone in the session can add songs.</p>}
          <ol className="space-y-1">
            {active.queue.map((s, i) => (
              <li key={`${s.id}-${i}`} className="flex items-center gap-3 rounded-md p-2 hover:bg-hover">
                <span className="w-5 text-right text-sm text-muted">{i + 1}</span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{s.title}</p><p className="truncate text-xs text-muted">{s.artist.name}</p></div>
                <span className="text-xs text-muted">{formatDuration(s.duration_ms)}</span>
                {isHost && <button onClick={() => control('queue_remove', { index: i })} aria-label={`Remove ${s.title}`} className="text-muted hover:text-white"><X className="size-4" /></button>}
              </li>
            ))}
          </ol>
        </section>
        <aside className="space-y-6">
          <section className="rounded-xl bg-surface p-5">
            <h3 className="mb-3 font-bold">People</h3>
            {[active.host, ...active.members].map((m) => (
              <div key={m.id} className="flex items-center gap-3 py-1.5">
                <div className="relative"><Avatar user={m} size="size-8" />
                  <span className={`absolute -bottom-0.5 -right-0.5 size-3 rounded-full ring-2 ring-surface ${online.has(m.id) ? 'bg-accent' : 'bg-zinc-600'}`}
                    aria-label={online.has(m.id) ? 'online' : 'offline'} /></div>
                <span className="flex-1 truncate text-sm">{m.display_name}</span>
                {m.id === active.host.id && <Crown className="size-4 text-amber-300" aria-label="Host" />}
              </div>
            ))}
          </section>
          <section className="rounded-xl bg-surface p-5">
            <h3 className="mb-3 font-bold">Add to the queue</h3>
            <AddToSession />
          </section>
        </aside>
      </div>
    </div>
  )
}
