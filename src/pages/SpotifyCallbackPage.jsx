import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { ErrorState, Spinner } from '../components/ui'
import { useSpotify } from '../context/SpotifyContext'
import { completeLogin } from '../lib/spotify'

/** Spotify redirects here after consent; exchange the code, then return to the app. */
export default function SpotifyCallbackPage() {
  const navigate = useNavigate()
  const { setConnected } = useSpotify()
  const [error, setError] = useState(null)
  const started = useRef(false) // StrictMode runs effects twice; a code can only be exchanged once

  useEffect(() => {
    if (started.current) return
    started.current = true
    completeLogin(window.location.search)
      .then(() => {
        setConnected(true)
        navigate('/account', { replace: true })
      })
      .catch((e) => setError(e))
  }, [navigate, setConnected])

  if (error) {
    return <ErrorState error={error} title="Couldn't connect Spotify" onRetry={() => navigate('/account', { replace: true })} />
  }
  return <div className="flex h-64 items-center justify-center gap-3 text-muted"><Spinner className="size-6 text-accent" /> Connecting to Spotify…</div>
}
