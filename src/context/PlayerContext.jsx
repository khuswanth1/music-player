import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { getAccessToken } from '../api/client'
import { catalogApi, libraryApi, podcastApi } from '../api/endpoints'
import { isEpisode, isUnavailable, songCover } from '../lib/tracks'
import { useAuth } from './AuthContext'
import { initialPlayerState, playerReducer } from './playerReducer'
import { useChannel } from './RealtimeContext'
import { useSpotify } from './SpotifyContext'
import { useToast } from './ToastContext'

const PlayerContext = createContext(null)
// Playback position ticks ~4x/second; it lives in its own context so only the seek bar re-renders, not every track list.
const PositionContext = createContext(0)
const STORAGE_KEY = 'wavely.player.v2' // v1 snapshots may hold tracks that are no longer offered (30-second previews)
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

  const spotify = useSpotify()
  const spotifyRef = useRef(spotify)
  spotifyRef.current = spotify
  const engineRef = useRef('audio') // 'audio' (our <audio>) or 'spotify' (the listener's own Spotify Premium device)
  const isPlayingRef = useRef(false)
  isPlayingRef.current = isPlaying
  const audioRef = useRef(null)
  const urlCache = useRef(new Map()) // songId -> { url, expiresAt }
  const pendingUrls = useRef(new Map()) // songId -> in-flight stream-url request
  const inflightRef = useRef(new Map())
  const wantPlayRef = useRef(false)
  const pendingSeekRef = useRef(null)
  const listenRef = useRef({ songId: null, ms: 0, lastTime: null, context: null })
  const restoredRef = useRef(false)
  const episodeRef = useRef({ item: null, positionMs: 0, reportedAt: 0 }) // podcast episode being listened to
  const retriedRef = useRef(null) // song id whose stream already got one fresh-URL retry
  const upgradeRef = useRef(null) // song id whose full stream we are still waiting for
  const failedRef = useRef(false) // the current song could not be loaded; Play must retry instead of doing nothing
  const swappingRef = useRef(false) // true while we pause the old song ourselves for a skip
  const srcRef = useRef('') // the src we set last; error events for any other src are stale and ignored
  const failuresRef = useRef(0) // consecutive songs that failed to play (stops auto-skip from looping)
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

  // --- podcast resume position + listening history -----------------------------------
  const flushEpisode = useCallback((completed = false) => {
    const e = episodeRef.current
    if (e.item && getAccessToken() && (e.positionMs >= 3000 || completed)) {
      podcastApi.progress(e.item, completed ? (e.item.duration_s || e.positionMs / 1000) : e.positionMs / 1000, completed).catch(() => {})
    }
    episodeRef.current = { ...e, reportedAt: Date.now() }
  }, [])

  // --- stream URLs (short-lived, song-scoped tokens) ---------------------------------
  const streamUrlFor = useCallback(async (songId, force = false) => {
    const cached = urlCache.current.get(songId)
    if (!force && cached && cached.expiresAt > Date.now() + 60_000) return cached.url
    // Share one request between a hover prefetch, the click and the queue look-ahead.
    const pending = !force && pendingUrls.current.get(songId)
    if (pending) return pending
    // fast: start on the short preview immediately if the full track isn't resolved yet; upgradeStream swaps it in later.
    const req = catalogApi.streamUrl(songId, true).then((res) => {
      urlCache.current.set(songId, { url: res.url, expiresAt: Date.now() + res.expires_in * 1000, upgrading: Boolean(res.upgrading) })
      return res.url
    }).finally(() => pendingUrls.current.delete(songId))
    pendingUrls.current.set(songId, req)
    return req
  }, [])

  // A song that started on a short preview: poll until the full stream is ready, then swap it in without losing the spot.
  const upgradeStream = useCallback(async (songId) => {
    upgradeRef.current = songId
    for (let i = 0; i < 30 && upgradeRef.current === songId; i++) {
      await new Promise((r) => setTimeout(r, 1500))
      if (upgradeRef.current !== songId) return
      let res
      try {
        res = await catalogApi.streamUrl(songId, true)
      } catch {
        break
      }
      if (res.upgrading) continue
      urlCache.current.set(songId, { url: res.url, expiresAt: Date.now() + res.expires_in * 1000, upgrading: false })
      const audio = audioRef.current
      if (upgradeRef.current !== songId || !audio || listenRef.current.songId !== songId) return
      const at = audio.currentTime
      const wasPlaying = !audio.paused || (wantPlayRef.current && audio.ended)
      audio.src = res.url
      srcRef.current = audio.src
      audio.addEventListener('loadedmetadata', () => { audio.currentTime = at }, { once: true })
      if (wasPlaying || wantPlayRef.current) audio.play().catch(() => {})
      break
    }
    if (upgradeRef.current === songId) {
      upgradeRef.current = null
      // Never got the full track: let a preview that ran out move on as usual.
      if (audioRef.current?.ended) dispatch({ type: 'next', auto: true })
    }
  }, [])

  // Load audio whenever the current song changes (or repeat-one restarts it).
  const currentId = current?.id
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !currentId) return undefined
    let cancelled = false
    flushListen(false)
    flushEpisode(false)
    retriedRef.current = null
    failedRef.current = false
    upgradeRef.current = null
    const episode = isEpisode(current)
    if (!episode && isUnavailable(current)) { // e.g. restored from an old queue: don't even ask the server, just move on
      setBuffering(false)
      if (stateRef.current.index + 1 < stateRef.current.queue.length) dispatch({ type: 'next' })
      else wantPlayRef.current = false
      return undefined
    }
    // Episodes aren't catalog songs: no stream-url call, no song listening history, and they resume where you left off.
    listenRef.current = { songId: episode ? null : currentId, ms: 0, lastTime: null, context: stateRef.current.context }
    episodeRef.current = { item: episode ? current : null, positionMs: 0, reportedAt: Date.now() }
    if (episode && pendingSeekRef.current == null && current.resume_ms > 5000 && current.resume_ms < (current.duration_ms || Infinity) - 10_000) {
      pendingSeekRef.current = current.resume_ms
    }
    setPosition(pendingSeekRef.current ?? 0)
    setDuration(current?.duration_ms || 0)
    setBuffering(true)
    // A track that is only a short preview here can play in full through the listener's own Spotify Premium account.
    const trySpotify = !episode && current.access === 'preview' && spotifyRef.current.ready && wantPlayRef.current
    if (engineRef.current === 'spotify') spotifyRef.current.pause?.()
    engineRef.current = 'audio'
    // Silence the previous song right away so Next/Previous feel instant instead of waiting on the network.
    if (!audio.paused) { swappingRef.current = true; audio.pause() }
    const startAudio = (url) => {
      audio.src = url
      srcRef.current = audio.src
      if (pendingSeekRef.current != null) {
        const seekTo = pendingSeekRef.current / 1000
        audio.addEventListener('loadedmetadata', () => { audio.currentTime = seekTo }, { once: true })
        pendingSeekRef.current = null
      }
      if (wantPlayRef.current) {
        audio.play().catch(() => { isPlayingRef.current = false; setIsPlaying(false) }) // autoplay may be blocked until the user interacts
      }
    }
    const source = trySpotify
      ? spotifyRef.current.resolve(current).then((uri) => (uri ? { uri } : streamUrlFor(currentId).then((url) => ({ url }))))
      : (episode
        ? (current.audio_url ? Promise.resolve(current.audio_url) : Promise.reject(Object.assign(new Error('This episode has no playable audio'), { code: 'audio_missing' })))
        : streamUrlFor(currentId)).then((url) => ({ url }))
    source
      .then(async ({ url, uri }) => {
        if (cancelled) return
        if (uri) {
          audio.pause()
          engineRef.current = 'spotify'
          try {
            await spotifyRef.current.play(uri, pendingSeekRef.current ?? 0)
            pendingSeekRef.current = null
            return
          } catch {
            engineRef.current = 'audio'
            toast.info("Spotify couldn't play this track; playing the preview instead")
            startAudio(await streamUrlFor(currentId))
            return
          }
        }
        startAudio(url)
        if (!episode && urlCache.current.get(currentId)?.upgrading) upgradeStream(currentId)
      })
      .catch((err) => {
        if (cancelled) return
        setBuffering(false)
        failedRef.current = true
        const skippable = SKIPPABLE.has(err.code) || err.status === 404 || err.status === 451
        if (skippable) toast.info("Skipped a track that isn't available here")
        else { toast.apiError(err, "Couldn't play this song"); setIsPlaying(false); wantPlayRef.current = false }
        if (skippable) {
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
      const ep = episodeRef.current
      if (ep.item) {
        ep.positionMs = t * 1000
        if (!audio.paused && Date.now() - ep.reportedAt > 15_000) flushEpisode(false)
      }
      const l = listenRef.current
      if (!audio.paused && l.lastTime != null) {
        const delta = t - l.lastTime
        if (delta > 0 && delta < 2) l.ms += delta * 1000 // ignore seeks
      }
      l.lastTime = t
    }
    const onPlay = () => { swappingRef.current = false; setIsPlaying(true); listenRef.current.lastTime = audio.currentTime }
    // A pause while we still intend to play is just the old song being cut for a skip: keep the button on "pause".
    const onPause = () => { if (swappingRef.current && !audio.ended) return; setIsPlaying(false); if (episodeRef.current.item) flushEpisode(false) }
    const onWaiting = () => setBuffering(true)
    const onPlaying = () => { setBuffering(false); failuresRef.current = 0 }
    const onMeta = () => {
      const s = stateRef.current
      const cur = s.index >= 0 ? s.queue[s.index] : null // read live: this handler outlives any one song
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        if (audio.duration <= 35 && (cur?.duration_ms || 0) > 35000) {
          setDuration(cur.duration_ms)
        } else {
          setDuration(audio.duration * 1000)
        }
      } else if (cur?.duration_ms) {
        setDuration(cur.duration_ms)
      }
      setBuffering(false)
    }
    // Give up on this song: say so once, then move on to the next one instead of leaving the player stuck.
    const failSong = () => {
      setBuffering(false)
      failedRef.current = true
      swappingRef.current = false
      setIsPlaying(false)
      toast.error('Playback failed for this song', { id: 'playback-failed' })
      failuresRef.current += 1
      const s = stateRef.current
      if (wantPlayRef.current && failuresRef.current < 3 && s.index + 1 < s.queue.length && !sessionRef.current) {
        dispatch({ type: 'next' })
      } else {
        wantPlayRef.current = false
      }
    }
    const onEnded = () => {
      if (upgradeRef.current && upgradeRef.current === listenRef.current.songId) { setBuffering(true); return } // preview ran out; the full track is about to swap in
      flushListen(true)
      if (episodeRef.current.item) flushEpisode(true)
      if (sessionRef.current) {
        if (sessionRef.current.isHost) sessionRef.current.controls.next()
        return
      }
      dispatch({ type: 'next', auto: true })
    }
    const onError = async () => {
      if (episodeRef.current.item) {
        // Publisher-hosted audio has no fresh-URL fallback: report it and move on.
        setBuffering(false)
        toast.error("This episode couldn't be played. The publisher's audio may be unavailable.")
        return
      }
      const songId = listenRef.current.songId
      // Stale error from a src we've already replaced (or never set): not about the song now playing.
      if (!songId || !srcRef.current || audio.src !== srcRef.current) return
      if (retriedRef.current === songId) {
        // Already retried with a fresh URL: the source itself is failing (e.g. a provider outage).
        failSong()
        return
      }
      retriedRef.current = songId
      // Most likely an expired stream token or signed provider URL: fetch a fresh URL once and resume.
      const at = audio.currentTime
      try {
        const url = await streamUrlFor(songId, true)
        if (listenRef.current.songId !== songId) return // the user moved on while we were fetching
        audio.src = url
        srcRef.current = audio.src
        if (at > 0) audio.addEventListener('loadedmetadata', () => { audio.currentTime = at }, { once: true })
        if (wantPlayRef.current) audio.play().catch(() => {})
      } catch {
        if (listenRef.current.songId === songId) failSong()
      }
    }
    const events = { timeupdate: onTime, play: onPlay, pause: onPause, waiting: onWaiting, playing: onPlaying,
      loadedmetadata: onMeta, ended: onEnded, error: onError }
    for (const [e, fn] of Object.entries(events)) audio.addEventListener(e, fn)
    return () => {
      for (const [e, fn] of Object.entries(events)) audio.removeEventListener(e, fn)
    }
  }, [flushListen, flushEpisode, streamUrlFor, toast])

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = state.muted ? 0 : state.volume
    spotifyRef.current.setVolume?.(state.muted ? 0 : state.volume)
  }, [state.volume, state.muted])

  // Spotify engine: mirror the SDK's state (it pushes changes, not progress, so poll while playing).
  const lastSpotify = useRef({ playing: false })
  useEffect(() => {
    spotifyRef.current.onState?.((s) => {
      if (engineRef.current !== 'spotify' || !s) return
      const wasPlaying = lastSpotify.current.playing
      lastSpotify.current = { playing: !s.paused }
      setIsPlaying(!s.paused)
      setPosition(s.position)
      setDuration(s.duration)
      setBuffering(Boolean(s.loading))
      // The SDK signals the end of a track as: paused, back at 0, with the track in `previous_tracks`.
      if (wasPlaying && s.paused && s.position === 0 && s.track_window?.previous_tracks?.length) dispatch({ type: 'next', auto: true })
    })
  }, [spotify.ready])
  useEffect(() => {
    if (!isPlaying || engineRef.current !== 'spotify') return undefined
    const t = setInterval(() => spotifyRef.current.getState?.().then((s) => s && engineRef.current === 'spotify' && setPosition(s.position)), 500)
    return () => clearInterval(t)
  }, [isPlaying])

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
    // Only tracks that can actually be played go into the queue; the start moves to the first playable one at or after it.
    const wanted = songs[startIndex]
    const playable = songs.filter((s) => s && !isUnavailable(s))
    if (!playable.length) {
      toast.info("None of these tracks can be played here")
      return
    }
    const after = songs.slice(startIndex).find((s) => s && !isUnavailable(s))
    startIndex = Math.max(0, playable.findIndex((s) => s.id === (after || wanted)?.id))
    if (sessionRef.current?.isHost) {
      sessionRef.current.controls.playSong(playable[startIndex])
      return
    }
    wantPlayRef.current = true
    failuresRef.current = 0
    setIsPlaying(true)
    const same = stateRef.current.queue[stateRef.current.index]?.id === playable[startIndex]?.id
    dispatch({ type: 'load', songs: playable, startIndex, context })
    if (same) {
      audioRef.current.currentTime = 0
      audioRef.current.play().catch(() => {})
    }
  }, [memberBlocked, toast])

  const play = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.play()
    wantPlayRef.current = true
    swappingRef.current = false
    isPlayingRef.current = true
    if (engineRef.current === 'spotify') return spotifyRef.current.resume()
    const audio = audioRef.current
    if (!audio) return
    if (audio.error || failedRef.current || !audio.getAttribute('src')) {
      // Nothing usable is loaded (a failed song, or still fetching the URL): (re)load the current track, which starts playing.
      if (stateRef.current.index >= 0 && (audio.error || failedRef.current)) {
        failuresRef.current = 0
        failedRef.current = false
        urlCache.current.clear()
        dispatch({ type: 'restart' })
      }
      setIsPlaying(true)
      return
    }
    setIsPlaying(true) // optimistic: the button flips on click, not after the audio element reports back
    audio.play().catch(() => { isPlayingRef.current = false; setIsPlaying(false) })
  }, [memberBlocked])

  const pause = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.pause()
    wantPlayRef.current = false
    swappingRef.current = false
    isPlayingRef.current = false
    setIsPlaying(false)
    if (engineRef.current === 'spotify') return spotifyRef.current.pause()
    audioRef.current?.pause()
  }, [memberBlocked])

  const toggle = useCallback(() => {
    if (!stateRef.current.queue.length && !sessionRef.current) return
    // Follow what the button shows (updated optimistically), not the audio element, which lags while a song loads.
    if (isPlayingRef.current) pause()
    else play()
  }, [play, pause])

  const seek = useCallback((ms) => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.seek(ms)
    if (engineRef.current === 'spotify') spotifyRef.current.seek(ms)
    else if (audioRef.current) audioRef.current.currentTime = ms / 1000
    setPosition(ms)
  }, [memberBlocked])

  const next = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.next()
    wantPlayRef.current = true
    failuresRef.current = 0
    flushListen(false)
    setIsPlaying(true)
    if (audioRef.current && !audioRef.current.paused) { swappingRef.current = true; audioRef.current.pause() } // cut the old song immediately
    dispatch({ type: 'next' })
  }, [memberBlocked, flushListen])

  const prev = useCallback(() => {
    if (memberBlocked()) return
    if (sessionRef.current?.isHost) return sessionRef.current.controls.prev?.()
    const seconds = engineRef.current === 'spotify' ? positionRef.current / 1000 : (audioRef.current?.currentTime || 0)
    if (seconds > 3) {
      seek(0)
      return
    }
    if (stateRef.current.index === 0 && !(stateRef.current.repeat === 'all' && stateRef.current.queue.length > 1)) {
      seek(0)
      return
    }
    wantPlayRef.current = true
    failuresRef.current = 0
    setIsPlaying(true)
    if (audioRef.current && !audioRef.current.paused) { swappingRef.current = true; audioRef.current.pause() }
    dispatch({ type: 'prev' })
  }, [memberBlocked, seek])

  const jumpTo = useCallback((index) => {
    if (memberBlocked()) return
    wantPlayRef.current = true
    failuresRef.current = 0
    setIsPlaying(true)
    dispatch({ type: 'jump', index })
  }, [memberBlocked])

  // Warm the next song's stream URL so Next / auto-advance starts without a network round trip.
  const nextId = state.index >= 0 ? state.queue[state.index + 1]?.id : null
  const nextIsEpisode = state.index >= 0 && isEpisode(state.queue[state.index + 1])
  useEffect(() => {
    if (nextId && !nextIsEpisode && getAccessToken()) streamUrlFor(nextId).catch(() => {})
  }, [nextId, nextIsEpisode, streamUrlFor])

  /** Warm a song's stream URL (e.g. on hover) so pressing play starts it with no lookup wait. Safe to call repeatedly. */
  const prefetch = useCallback((song) => {
    if (!song?.id || isEpisode(song) || isUnavailable(song) || !getAccessToken()) return
    if (inflightRef.current.has(song.id)) return
    inflightRef.current.set(song.id, streamUrlFor(song.id).catch(() => {}).finally(() => inflightRef.current.delete(song.id)))
  }, [streamUrlFor])

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
        // Skip anything that can't be played any more (e.g. a 30-second preview that is now hidden).
        const queue = [server.current_song, ...server.queue].filter((s) => s && !isUnavailable(s))
        if (queue.length) {
          pendingSeekRef.current = queue[0].id === server.current_song.id ? server.position_ms : null
          dispatch({ type: 'restore', state: { queue, index: 0,
            shuffle: server.shuffle, repeat: server.repeat_mode, volume: server.volume, context: server.context } })
        }
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
    if (toServer && !isEpisode(s.queue[s.index])) { // episodes resume through their own progress endpoint
      libraryApi.savePlayer({
        current_song_id: s.queue[s.index]?.id || null, position_ms: snapshot.position,
        queue: s.queue.slice(s.index + 1, s.index + 201).filter((x) => !isEpisode(x)).map((x) => x.id), context: s.context,
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
    ...state, current, isPlaying, duration, buffering, session, getPosition: () => positionRef.current,
    playList, play, pause, toggle, seek, next, prev, jumpTo, addToQueue, follow, setSession, prefetch,
    removeFromQueue: (index) => dispatch({ type: 'remove', index }),
    toggleShuffle: () => dispatch({ type: 'toggleShuffle' }),
    cycleRepeat: () => dispatch({ type: 'cycleRepeat' }),
    setVolume: (v) => dispatch({ type: 'volume', value: v }),
    toggleMute: () => dispatch({ type: 'toggleMute' }),
  }), [state, current, isPlaying, duration, buffering, session, playList, play, pause, toggle, seek, next,
    prev, jumpTo, addToQueue, follow, prefetch])

  return (
    <PlayerContext.Provider value={value}>
      <PositionContext.Provider value={position}>{children}</PositionContext.Provider>
    </PlayerContext.Provider>
  )
}

export function usePlayerPosition() {
  return useContext(PositionContext)
}

export function usePlayer() {
  return useContext(PlayerContext)
}
