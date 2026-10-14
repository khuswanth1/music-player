import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { sessionApi } from '../api/endpoints'
import { useAuth } from './AuthContext'
import { usePlayer } from './PlayerContext'
import { useChannel, useRealtime } from './RealtimeContext'
import { useToast } from './ToastContext'

const SessionContext = createContext(null)
const KEY = 'wavely.session'

/** Where the shared playhead is right now, correcting for client/server clock skew. */
export function livePosition(s, receivedAt = Date.now()) {
  if (!s) return 0
  let pos = s.position_ms
  if (s.is_playing) {
    const skew = receivedAt - Date.parse(s.server_time)
    pos += Math.max(0, Date.now() - skew - Date.parse(s.state_updated_at))
  }
  return Math.min(pos, s.current_song?.duration_ms ?? pos)
}

export function SessionProvider({ children }) {
  const { status, user } = useAuth()
  const { send } = useRealtime()
  const player = usePlayer()
  const toast = useToast()
  const [active, setActive] = useState(null)
  const [presence, setPresence] = useState([])
  const receivedAtRef = useRef(Date.now())
  const followRef = useRef(player.follow)
  followRef.current = player.follow

  const apply = useCallback((s, isHost) => {
    receivedAtRef.current = Date.now()
    setActive({ ...s, is_host: isHost })
    followRef.current({ song: s.current_song, positionMs: livePosition(s), playing: s.is_playing })
  }, [])

  const clear = useCallback(() => {
    setActive(null)
    setPresence([])
    localStorage.removeItem(KEY)
    player.setSession(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.setSession])

  // Resume a session after reload.
  useEffect(() => {
    if (status !== 'authenticated') return
    const id = localStorage.getItem(KEY)
    if (!id) return
    sessionApi.get(id).then((s) => (s.is_active ? apply(s, s.is_host) : clear())).catch(clear)
  }, [status, apply, clear])

  useEffect(() => {
    if (status === 'anonymous') clear()
  }, [status, clear])

  const control = useCallback((action, extra = {}) => {
    if (!active) return
    send({ type: 'session.control', session_id: active.id, action, ...extra })
  }, [active, send])

  // Hand the player its session hooks: host actions become session commands.
  useEffect(() => {
    if (!active) return
    player.setSession({
      id: active.id, name: active.name, isHost: active.is_host,
      controls: {
        play: () => control('play'),
        pause: () => control('pause'),
        seek: (ms) => control('seek', { position_ms: Math.round(ms) }),
        next: () => control('next'),
        prev: () => control('prev'),
        playSong: (song) => control('play_song', { song_id: song.id }),
        queueAdd: (song) => {
          control('queue_add', { song_id: song.id })
          toast.success(`Added to ${active.name}`)
        },
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, active?.is_host, active?.name, control])

  useChannel(active ? `session:${active.id}` : null, (msg) => {
    if (msg.type === 'session.state') apply(msg.session, active?.is_host)
    else if (msg.type === 'presence') setPresence(msg.users)
    else if (msg.type === 'session.ended') {
      if (!active?.is_host) toast.info('The host ended the session')
      followRef.current({ song: null })
      clear()
    }
  })

  useChannel(active ? '*errors' : null, (msg) => {
    if (msg.code && msg.message) toast.error(msg.message)
  })

  const start = useCallback(async (name) => {
    const s = await sessionApi.create(name)
    localStorage.setItem(KEY, s.id)
    apply(s, true)
    return s
  }, [apply])

  const join = useCallback(async (code) => {
    const s = await sessionApi.join(code)
    localStorage.setItem(KEY, s.id)
    apply(s, s.is_host)
    return s
  }, [apply])

  const leave = useCallback(async () => {
    if (!active) return
    try {
      await (active.is_host ? sessionApi.end(active.id) : sessionApi.leave(active.id))
    } finally {
      followRef.current({ song: null })
      clear()
    }
  }, [active, clear])

  const value = useMemo(() => ({
    active, presence, start, join, leave, control, isHost: Boolean(active?.is_host), userId: user?.id,
  }), [active, presence, start, join, leave, control, user?.id])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  return useContext(SessionContext)
}
