import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { Check, Music2 } from 'lucide-react'
import { catalogApi, libraryApi, musicApi, worldApi } from '../api/endpoints'
import { Cover, Spinner, inputClass } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useApi, useDebounce } from '../hooks/useApi'
import { useLanguages } from '../lib/languages'

// First-run flow: languages -> genres ("music journey") -> artists. Every step is optional and has a Skip, nothing is
// saved until the person moves on, and leaving at any point lands on the normal home screen.
const STEPS = [
  { title: 'Which languages do you listen to?', hint: 'Pick as many as you like. We’ll show more music in them — you can change this anytime.' },
  { title: 'What’s your music journey?', hint: 'Choose the sounds you love and we’ll tune your recommendations.' },
  { title: 'Follow a few singers', hint: 'Their new music will show up on your home screen.' },
]

// Card colours, picked by language code so each language keeps its own colour between visits.
const CARD_COLORS = ['#1e6b4f', '#8d3b72', '#2a5db0', '#b0552a', '#6b4fbf', '#a8324a', '#2f7d8c', '#7a6a1e', '#3d6b2a', '#a1448f']
const colorFor = (code) => CARD_COLORS[[...code].reduce((n, c) => n + c.charCodeAt(0), 0) % CARD_COLORS.length]

function LanguageStep({ picked, toggle }) {
  const languages = useLanguages()
  const shown = useMemo(() => languages.filter((l) => l.featured || l.playable_count > 0), [languages])
  if (!languages.length) return <div className="flex justify-center py-16"><Spinner className="size-7 text-accent" /></div>
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {shown.map((l) => {
        const on = picked.includes(l.code)
        const native = l.native_name && l.native_name !== l.name ? l.native_name : null
        return (
          <button key={l.code} type="button" aria-pressed={on} onClick={() => toggle(l.code)}
            style={{ backgroundImage: `linear-gradient(135deg, ${colorFor(l.code)}, ${colorFor(l.code)}99)` }}
            className={`relative flex h-28 min-w-0 flex-col justify-between overflow-hidden rounded-xl p-3 text-left text-white transition active:scale-95 ${
              on ? 'ring-4 ring-white' : 'ring-1 ring-white/10 hover:brightness-110'}`}>
            <span className="line-clamp-1 text-2xl font-extrabold leading-tight" lang={l.code}>{native || l.name}</span>
            <span className="text-sm font-semibold text-white/80">{l.name}</span>
            {on && <span className="absolute right-2 top-2 rounded-full bg-white p-1 text-black"><Check className="size-3.5" aria-hidden /></span>}
          </button>
        )
      })}
    </div>
  )
}

function GenreStep({ picked, toggle }) {
  const { data: genres, error } = useApi(() => catalogApi.genres(), [])
  if (error) return <p className="py-10 text-center text-sm text-muted">Couldn’t load genres right now — you can skip this step.</p>
  if (!genres) return <div className="flex justify-center py-16"><Spinner className="size-7 text-accent" /></div>
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {genres.map((g) => {
        const on = picked.includes(g.slug)
        return (
          <button key={g.id} type="button" aria-pressed={on} onClick={() => toggle(g.slug)}
            style={{ backgroundColor: g.color || '#2a2a2a' }}
            className={`relative flex h-24 items-end rounded-lg p-3 text-left text-base font-extrabold text-white transition active:scale-95 ${on ? 'ring-4 ring-white' : 'hover:brightness-110'}`}>
            {g.name}
            {on && <span className="absolute right-2 top-2 rounded-full bg-white p-1 text-black"><Check className="size-3.5" aria-hidden /></span>}
          </button>
        )
      })}
    </div>
  )
}

// Well-known voices to jump-start a search, including the older generation. Tapping one searches live across the
// music sources, so they can be followed even when the local catalog has nothing for them yet.
const LEGENDS = {
  te: ['S. P. Balasubrahmanyam', 'Ghantasala', 'P. Susheela', 'S. Janaki', 'Ilaiyaraaja'],
  hi: ['Kishore Kumar', 'Lata Mangeshkar', 'Mohammed Rafi', 'Asha Bhosle', 'Mukesh'],
  ta: ['T. M. Soundararajan', 'K. J. Yesudas', 'K. S. Chithra', 'S. P. Balasubrahmanyam', 'Ilaiyaraaja'],
  kn: ['Dr. Rajkumar', 'P. B. Sreenivas', 'Vani Jairam', 'S. Janaki'],
  ml: ['K. J. Yesudas', 'K. S. Chithra', 'P. Jayachandran', 'S. Janaki'],
  bn: ['Hemanta Mukherjee', 'Manna Dey', 'Kishore Kumar', 'Sandhya Mukhopadhyay'],
  pa: ['Gurdas Maan', 'Surinder Kaur', 'Kuldeep Manak', 'Mohammed Sadiq'],
  mr: ['Lata Mangeshkar', 'Asha Bhosle', 'Suresh Wadkar', 'Sudhir Phadke'],
  ur: ['Nusrat Fateh Ali Khan', 'Mehdi Hassan', 'Noor Jehan', 'Ghulam Ali'],
  en: ['Frank Sinatra', 'Elvis Presley', 'The Beatles', 'Michael Jackson', 'Whitney Houston'],
}

// Upload-channel style names ("#SWAMI_SUNDARA...", "UESI-AP") are not singers people want to follow.
const looksLikeSinger = (a) => a?.name && !/^[#@]/.test(a.name) && !/_/.test(a.name) && !/official|channel|\.com/i.test(a.name)

function ArtistStep({ languages, picked, toggle }) {
  const [q, setQ] = useState('')
  const term = useDebounce(q.trim(), 400)
  const searching = term.length >= 2
  // The people shown follow the languages chosen earlier (a good number of each, so older and newer singers both
  // appear); with no languages it is simply the most-played artists.
  const key = languages.join(',')
  const browse = useApi(async (signal) => {
    const picks = languages.length ? languages.slice(0, 4) : [undefined]
    const lists = await Promise.all(picks.map((language) => worldApi.catalogArtists({ language, limit: languages.length ? 30 : 48 }, signal)))
    const seen = new Set()
    // Interleave the languages so the first screen has some of each rather than all of the biggest one.
    const rows = Array.from({ length: Math.max(...lists.map((l) => l.length)) }, (_, i) => lists.map((l) => l[i])).flat()
    return rows.filter((a) => a && looksLikeSinger(a) && !seen.has(a.id) && seen.add(a.id))
  }, [key])
  const found = useApi((signal) => (searching ? worldApi.searchArtists({ q: term }, signal) : Promise.resolve(null)), [term, searching])
  const legends = useMemo(() => [...new Set(languages.flatMap((l) => LEGENDS[l] || []))].slice(0, 8), [languages])

  const artists = searching ? (found.data?.items || []).filter(looksLikeSinger) : browse.data
  const loading = searching ? found.loading : !browse.data && !browse.error

  // Real portraits: artwork on a song is not a picture of the singer, so photos are looked up by name and fill in as
  // they arrive. Until then (or if none exists) the card shows a neutral placeholder, never an album cover.
  const [photos, setPhotos] = useState({})
  const wanted = (artists || []).filter((a) => !a.image_url && !(a.id in photos)).map((a) => a.id).join(',')
  useEffect(() => {
    if (!wanted) return undefined
    let alive = true
    worldApi.artistPhotos(wanted.split(',').slice(0, 40))
      .then((found) => alive && setPhotos((p) => ({ ...p, ...Object.fromEntries(wanted.split(',').map((id) => [id, null])), ...found })))
      .catch(() => alive && setPhotos((p) => ({ ...p, ...Object.fromEntries(wanted.split(',').map((id) => [id, null])) })))
    return () => {
      alive = false
    }
  }, [wanted])
  return (
    <div>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search any singer, old or new"
        aria-label="Search singers" className={`${inputClass} mb-3`} />
      {legends.length > 0 && !searching && (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-subtle">Legends</span>
          {legends.map((name) => (
            <button key={name} type="button" onClick={() => setQ(name)}
              className="rounded-full bg-elevated px-3 py-1.5 text-xs font-semibold ring-1 ring-line hover:bg-hover active:scale-95">{name}</button>
          ))}
        </div>
      )}
      {loading && <div className="flex justify-center py-12"><Spinner className="size-7 text-accent" /></div>}
      {!loading && !searching && browse.error && <p className="py-10 text-center text-sm text-muted">Couldn’t load artists right now — search for a singer or skip this step.</p>}
      {!loading && artists && artists.length === 0 && (
        <p className="py-10 text-center text-sm text-muted">{searching ? 'No singers found — check the spelling.' : 'No artists to suggest yet — search for your favourites above.'}</p>
      )}
      {!loading && artists?.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(7rem,1fr))] gap-x-3 gap-y-5">
          {artists.map((a) => {
            const on = picked.includes(a.id)
            return (
              <button key={a.id} type="button" aria-pressed={on} onClick={() => toggle(a.id)}
                className="group flex min-w-0 flex-col items-center gap-2 text-center active:scale-95">
                <span className="relative block w-full max-w-28">
                  <Cover src={a.image_url || photos[a.id]} seed={a.id} alt="" rounded="rounded-full" icon={Music2}
                    className={`w-full transition ${on ? 'ring-4 ring-accent' : 'group-hover:brightness-110'}`} />
                  {on && <span className="absolute bottom-0 right-0 rounded-full bg-accent p-1 text-black"><Check className="size-4" aria-hidden /></span>}
                </span>
                <span className="line-clamp-2 w-full min-w-0 text-sm font-semibold [overflow-wrap:anywhere]" title={a.name}>{a.name}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function OnboardingPage() {
  const { user, completeOnboarding } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [languages, setLanguages] = useState([])
  const [genres, setGenres] = useState([])
  const [artists, setArtists] = useState([])
  const topRef = useRef(null)
  const flip = (setter) => (value) => setter((list) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]))

  useEffect(() => { topRef.current?.scrollTo?.(0, 0) }, [step])

  const finish = (followArtists) => {
    // Home is shown at once; the choices are saved in the background.
    if (followArtists && artists.length) Promise.all(artists.map((id) => libraryApi.follow(id).catch(() => {})))
    completeOnboarding(genres.length ? genres : undefined)
    navigate('/', { replace: true })
  }

  // Each step can be skipped or continued; either way the next screen appears immediately and saving happens behind it.
  const advance = (keep) => {
    if (step === 0 && keep && languages.length) musicApi.setMyLanguages(languages).catch(() => {})
    if (step < STEPS.length - 1) {
      // Choices from a step that was skipped are not applied.
      if (!keep && step === 0) setLanguages([])
      if (!keep && step === 1) setGenres([])
      setStep(step + 1)
      return
    }
    finish(keep)
  }

  const picked = [languages, genres, artists][step]
  const last = step === STEPS.length - 1
  const { title, hint } = STEPS[step]

  return (
    <div ref={topRef} className="flex h-dvh flex-col bg-gradient-to-b from-[#1f3a2a] via-surface to-black">
      <header className="flex items-center justify-between px-5 py-4 md:px-10">
        <span className="flex items-center gap-2 text-lg font-extrabold"><Music2 className="size-6 text-accent" aria-hidden /> Wavely</span>
        <div className="flex items-center gap-2" role="progressbar" aria-valuemin={1} aria-valuemax={STEPS.length} aria-valuenow={step + 1} aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((_, i) => <span key={i} className={`h-1.5 rounded-full transition-all ${i === step ? 'w-8 bg-accent' : i < step ? 'w-4 bg-accent/60' : 'w-4 bg-white/20'}`} />)}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 md:px-10">
        <div className="mx-auto max-w-3xl">
          <h1 className="mt-2 text-center text-3xl font-extrabold tracking-tight md:text-4xl">
            {step === 0 && user?.display_name ? `Welcome, ${user.display_name.split(' ')[0]}! ` : ''}{title}
          </h1>
          <p className="mx-auto mb-8 mt-2 max-w-xl text-center text-sm text-muted">{hint}</p>
          {step === 0 && <LanguageStep picked={languages} toggle={flip(setLanguages)} />}
          {step === 1 && <GenreStep picked={genres} toggle={flip(setGenres)} />}
          {step === 2 && <ArtistStep languages={languages} picked={artists} toggle={flip(setArtists)} />}
        </div>
      </main>

      <footer className="border-t border-line bg-black/60 px-5 py-4 backdrop-blur md:px-10">
        <div className="mx-auto flex max-w-3xl flex-col items-center gap-3 sm:flex-row-reverse sm:justify-between">
          <button type="button" onClick={() => advance(true)} disabled={!picked.length}
            className="w-full rounded-full bg-accent px-10 py-3 text-sm font-bold text-black transition hover:bg-accent-strong active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto">
            {last ? (picked.length ? `Follow ${picked.length} & start listening` : 'Start listening') : `Continue${picked.length ? ` (${picked.length})` : ''}`}
          </button>
          <button type="button" onClick={() => advance(false)}
            className="text-sm font-bold text-muted underline-offset-4 hover:text-white hover:underline">
            Skip
          </button>
        </div>
      </footer>
    </div>
  )
}
