import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { getAccessToken } from '../api/client'
import { catalogApi, libraryApi } from '../api/endpoints'
import { songCover } from '../lib/tracks'
import { useAuth } from './AuthContext'
import { initialPlayerState, playerReducer } from './playerReducer'
import { useChannel } from './RealtimeContext'
import { useToast } from './ToastContext'

const PlayerContext = createContext(null)
const STORAGE_KEY = 'wavely.player.v1'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
// Errors after which we move on to the next song instead of stopping.
const SKIPPABLE = new Set(['premium_required', 'playback_restricted', 'source_disabled', 'audio_missing'])

function readLocal() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || null
  } catch {
    return null
  }
}

export function PlayerProvider({ children }) {
  const { status: authStatus, user } = useAuth()
  const toast = useToast()
  const [state, dispatch] = useReducer(playerReducer, initialPlayerState)
  const [isPlaying, setIsPlaying] = useState(false)
  const [position, setPosition] = useState(0) // ms
  const [duration, setDuration] = useState(0) // ms
  const [buffering, setBuffering] = useState(false)
  const [session, setSession] = useState(null) // { id, name, isHost, controls }

  const audioRef = useRef(null)
  const urlCache = useRef(new Map()) // songId -> { url, expiresAt }
  const wantPlayRef = useRef(false)
  const pendingSeekRef = useRef(null)
  const listenRef = useRef({ songId: null, ms: 0, lastTime: null, context: null })
  const restoredRef = useRef(false)
  const retriedRef = useRef(null) // song id whose stream already got one fresh-URL retry
  const stateRef = useRef(state)
  stateRef.current = state
  const sessionRef = useRef(session)
  sessionRef.current = session

  const current = state.index >= 0 ? state.queue[state.index] : null

  if (!audioRef.current && typeof Audio !== 'undefined') {
    audioRef.current = new Audio()
    audioRef.current.preload = 'auto'
  }

  // --- listening history -------------------------------------------------------------
  const flushListen = useCallback((completed = false) => {
    const l = listenRef.current
    if (l.songId && l.ms >= 1000 && getAccessToken()) {
      libraryApi.recordPlay({
        song_id: l.songId, ms_played: Math.round(l.ms), completed,
        // Some contexts (genre slug, Liked Songs) have no UUID; the type alone is still recorded.
        context_type: l.context?.type || null, context_id: UUID.test(l.context?.id || '') ? l.context.id : null,
      }).catch(() => {})
    }
    listenRef.current = { songId: null, ms: 0, lastTime: null, context: null }
  }, [])

  // --- stream URLs (short-lived, song-scoped tokens) ---------------------------------
  const streamUrlFor = useCallback(async (songId, force = false) => {
    const cached = urlCache.current.get(songId)
    if (!force && cached && cached.expiresAt > Date.now() + 60_000) return cached.url
    const res = await catalogApi.streamUrl(songId)
    urlCache.current.set(songId, { url: res.url, expiresAt: Date.now() + res.expires_in * 1000 })
    return res.url
  }, [])

  // Load audio whenever the current song changes (or repeat-one restarts it).
  const currentId = current?.id
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !currentId) return undefined
    let cancelled = false
    flushListen(false)
    retriedRef.current = null
    listenRef.current = { songId: currentId, ms: 0, lastTime: null, context: stateRef.current.context }
    setPosition(pendingSeekRef.current ?? 0)
    setDuration(current?.duration_ms || 0)
    setBuffering(true)
    streamUrlFor(currentId)
      .then((url) => {
        if (cancelled) return
        audio.src = url
        if (pendingSeekRef.current != null) {
          const seekTo = pendingSeekRef.current / 1000
          audio.addEventListener('loadedmetadata', () => { audio.currentTime = seekTo }, { once: true })
          pendingSeekRef.current = null
        }
        if (wantPlayRef.current) {
          audio.play().catch(() => setIsPlaying(false)) // autoplay may be blocked until the user interacts
        }
      })
      .catch((err) => {
        if (cancelled) return
        setBuffering(false)
        toast.apiError(err, "Couldn't play this song")
        if (SKIPPABLE.has(err.code) || err.status === 404 || err.status === 451) {
          // skip to the next playable song
          if (stateRef.current.index + 1 < stateRef.current.queue.length) dispatch({ type: 'next' })
          else wantPlayRef.current = false
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId, state.restartToken])

  // Reaching the end of the queue with repeat off.
  useEffect(() => {
    if (state.ended) {
      wantPlayRef.current = false
      audioRef.current?.pause()
    }
  }, [state.ended])

  // --- audio element events ------------------------------------------------------------
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return undefined
    const onTime = () => {
      const t = audio.currentTime
      setPosition(t * 1000)
      const l = listenRef.current
      if (!audio.paused && l.lastTime != null) {
        const delta = t - l.lastTime
        if (delta > 0 && delta < 2) l.ms += delta * 1000 // ignore seeks
      }
      l.lastTime = t
    }
    const onPlay = () => { setIsPlaying(true); listenRef.current.lastTime = audio.currentTime }
    const onPause = () => setIsPlaying(false)
    const onWaiting = () => setBuffering(true)
    const onPlaying = () => setBuffering(false)
    const onMeta = () => { setDuration(audio.duration * 1000); setBuffering(false) }
    const onEnded = () => {
      flushListen(true)
      if (sessionRef.current) {
        if (sessionRef.current.isHost) sessionRef.current.controls.next()
        return
      }
      dispatch({ type: 'next', auto: true })
    }
    const onError = async () => {
      const songId = listenRef.current.songId
      if (!audio.src || !songId) return
      if (retriedRef.current === songId) {
        // Already retried with a fresh URL: the source itself is failing (e.g. a provider outage).
        setBuffering(false)
        toast.error('Playback failed for this song')
        return
      }
      retriedRef.current = songId
      // Most likely an expired stream token or signed provider URL: fetch a fresh URL once and resume.
      const at = audio.currentTime
      try {
        const url = await streamUrlFor(songId, true)
        audio.src = url
        audio.currentTime = at
        if (wantPlayRef.current) await audio.play()
      } catch {
        setBuffering(false)
        toast.error('Playback failed for this song')
      }
    }
    const events = { timeupdate: onTime, play: onPlay, pause: onPause, waiting: onWaiting, playing: onPlaying,
      loadedmetadata: onMeta, ended: onEnded, error: onError }
    for (const [e, fn] of Object.entries(events)) audio.addEventListener(e, fn)
    return () => {
      for (const [e, fn] of Object.entries(events)) audio.removeEventListener(e, fn)
    }
  }, [flushListen, streamUrlFor, toast])

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = state.muted ? 0 : state.volume
  }, [state.volume, state.muted])

  // --- controls ------------------------------------------------------------------------
  const memberBlocked = useCallback(() => {
    const s = sessionRef.current
    if (s && !s.isHost) {
      toast.info(`The host controls playback in "${s.name}"`)
      return true
    }
    return false
  }, [toast])

  const playList = useCallback((songs, startIndex = 0, context = null) => {
    if (memberBlocked()) return
    const playable = songs.filter(Boolean)
    if (!playable.length) return
    if (sessionRef.current?.isHost) {
      sessionRef.current.controls.playSong(playable[startIndex])
      return
    }
    wantPlayRef.current = true
    const same = stateRef.current.queue[stateRef.current.index]?.id === playable[startIndex]?.id
    dispatch({ type: 'load', songs: playable, startIndex, context })
    if (same) {
      audioRef.current.currentTime = 0
      audioRef.current.play().catch(() => {})
    }
  }, [memberBlocked])

  const play = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.play()
    wantPlayRef.current = true
    audioRef.current?.play().catch(() => {})
  }, [memberBlocked])

  const pause = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.pause()
    wantPlayRef.current = false
    audioRef.current?.pause()
  }, [memberBlocked])

  const toggle = useCallback(() => {
    if (!stateRef.current.queue.length && !sessionRef.current) return
    if (audioRef.current?.paused) play()
    else pause()
  }, [play, pause])

  const seek = useCallback((ms) => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.seek(ms)
    if (audioRef.current) audioRef.current.currentTime = ms / 1000
    setPosition(ms)
  }, [memberBlocked])

  const next = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.next()
    wantPlayRef.current = true
    flushListen(false)
    dispatch({ type: 'next' })
  }, [memberBlocked, flushListen])

  const prev = useCallback(() => {
    if (memberBlocked()) return
    if ((audioRef.current?.currentTime || 0) > 3 || stateRef.current.index === 0) {
      seek(0)
      return
    }
    wantPlayRef.current = true
    dispatch({ type: 'prev' })
  }, [memberBlocked, seek])

  const jumpTo = useCallback((index) => {
    if (memberBlocked()) return
    wantPlayRef.current = true
    dispatch({ type: 'jump', index })
  }, [memberBlocked])

  const addToQueue = useCallback((song) => {
    if (sessionRef.current) {
      sessionRef.current.controls.queueAdd(song)
      return
    }
    dispatch({ type: 'enqueue', song })
    toast.success('Added to queue')
  }, [toast])

  /** Called by the group-session layer: mirror the shared state locally. */
  const follow = useCallback(({ song, positionMs, playing }) => {
    const audio = audioRef.current
    if (!song) {
      audio?.pause()
      return
    }
    wantPlayRef.current = playing
    if (stateRef.current.queue[stateRef.current.index]?.id !== song.id) {
      pendingSeekRef.current = positionMs
      dispatch({ type: 'load', songs: [song], startIndex: 0, context: { type: 'session' } })
      return
    }
    if (Math.abs(audio.currentTime * 1000 - positionMs) > 1500) audio.currentTime = positionMs / 1000
    if (playing && audio.paused) audio.play().catch(() => {})
    if (!playing && !audio.paused) audio.pause()
  }, [])

  // --- persistence ---------------------------------------------------------------------
  // Restore once per sign-in: whichever of the local and server copies is newer wins.
  useEffect(() => {
    if (authStatus !== 'authenticated' || restoredRef.current) return
    restoredRef.current = true
    const local = readLocal()
    libraryApi.player().then((server) => {
      const serverTime = server.updated_at ? new Date(server.updated_at).getTime() : 0
      const useLocal = local && local.userId === user?.id && (local.savedAt || 0) > serverTime
      if (useLocal && local.queue?.length) {
        pendingSeekRef.current = local.position || 0
        dispatch({ type: 'restore', state: { queue: local.queue, index: local.index, shuffle: local.shuffle,
          repeat: local.repeat, volume: local.volume ?? 0.8, context: local.context } })
      } else if (server.current_song) {
        pendingSeekRef.current = server.position_ms
        dispatch({ type: 'restore', state: { queue: [server.current_song, ...server.queue], index: 0,
          shuffle: server.shuffle, repeat: server.repeat_mode, volume: server.volume, context: server.context } })
      }
    }).catch(() => {})
  }, [authStatus, user?.id])

  useEffect(() => {
    if (authStatus === 'anonymous') {
      restoredRef.current = false
      wantPlayRef.current = false
      audioRef.current?.pause()
      dispatch({ type: 'restore', state: initialPlayerState })
    }
  }, [authStatus])

  const positionRef = useRef(0)
  positionRef.current = position
  const persist = useCallback((toServer) => {
    const s = stateRef.current
    if (!user || s.index < 0 || sessionRef.current) return
    const snapshot = { userId: user.id, queue: s.queue.slice(Math.max(0, s.index - 50), s.index + 200),
      index: Math.min(s.index, 50), position: Math.round(positionRef.current), shuffle: s.shuffle,
      repeat: s.repeat, volume: s.volume, context: s.context, savedAt: Date.now() }
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
    } catch {
      /* storage full or disabled */
    }
    if (toServer) {
      libraryApi.savePlayer({
        current_song_id: s.queue[s.index]?.id || null, position_ms: snapshot.position,
        queue: s.queue.slice(s.index + 1, s.index + 201).map((x) => x.id), context: s.context,
        shuffle: s.shuffle, repeat_mode: s.repeat, volume: s.volume,
      }).catch(() => {})
    }
  }, [user])

  // Save locally on every queue change and every few seconds of playback; sync the server less often.
  useEffect(() => { persist(false) }, [state.queue, state.index, state.shuffle, state.repeat, state.volume, persist])
  useEffect(() => {
    const local = setInterval(() => persist(false), 5000)
    const remote = setInterval(() => persist(true), 20000)
    const onHide = () => persist(true)
    window.addEventListener('pagehide', onHide)
    return () => {
      clearInterval(local)
      clearInterval(remote)
      window.removeEventListener('pagehide', onHide)
    }
  }, [persist])
  useEffect(() => {
    if (!isPlaying) persist(true) // pausing is a natural sync point
  }, [isPlaying, persist])

  // --- OS media controls (lock screen, hardware keys) ----------------------------------
  useEffect(() => {
    if (!('mediaSession' in navigator) || !current) return
    navigator.mediaSession.metadata = new window.MediaMetadata({
      title: current.title, artist: current.artist?.name, album: current.album?.title || '',
      artwork: songCover(current) ? [{ src: songCover(current), sizes: '512x512' }] : [],
    })
    const handlers = { play, pause, nexttrack: next, previoustrack: prev,
      seekto: (d) => seek(d.seekTime * 1000) }
    for (const [action, fn] of Object.entries(handlers)) {
      try {
        navigator.mediaSession.setActionHandler(action, fn)
      } catch {
        /* unsupported action */
      }
    }
  }, [current, play, pause, next, prev, seek])

  // A takedown or provider removal can make the playing song unplayable mid-session.
  useChannel(authStatus === 'authenticated' ? 'catalog' : null, (msg) => {
    if (msg.type !== 'track.unavailable') return
    urlCache.current.delete(msg.song_id)
    const s = stateRef.current
    if (s.queue[s.index]?.id === msg.song_id && !sessionRef.current) {
      toast.info('This track is no longer available here')
      if (s.index + 1 < s.queue.length) dispatch({ type: 'next' })
      else {
        wantPlayRef.current = false
        audioRef.current?.pause()
      }
    }
  })

  const value = useMemo(() => ({
    ...state, current, isPlaying, position, duration, buffering, session,
    playList, play, pause, toggle, seek, next, prev, jumpTo, addToQueue, follow, setSession,
    removeFromQueue: (index) => dispatch({ type: 'remove', index }),
    toggleShuffle: () => dispatch({ type: 'toggleShuffle' }),
    cycleRepeat: () => dispatch({ type: 'cycleRepeat' }),
    setVolume: (v) => dispatch({ type: 'volume', value: v }),
    toggleMute: () => dispatch({ type: 'toggleMute' }),
  }), [state, current, isPlaying, position, duration, buffering, session, playList, play, pause, toggle, seek, next,
    prev, jumpTo, addToQueue, follow])

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
}

export function usePlayer() {
  return useContext(PlayerContext)
}
