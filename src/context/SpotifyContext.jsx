import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { accessToken, beginLogin, clientId, disconnect as forget, findTrack, isConnected, loadSdk, playOn } from '../lib/spotify'

const SpotifyContext = createContext({ enabled: false, connected: false, ready: false })

/**
 * Owns the Spotify Web Playback SDK device. PlayerContext uses it as a second playback engine for tracks that are
 * only previews here: `resolve` finds the same recording on Spotify and `play` starts it on this browser's device.
 */
export function SpotifyProvider({ children }) {
  const enabled = Boolean(clientId())
  const [connected, setConnected] = useState(() => enabled && isConnected())
  const [deviceId, setDeviceId] = useState(null)
  const [problem, setProblem] = useState(null)
  const playerRef = useRef(null)
  const deviceRef = useRef(null)
  const handlerRef = useRef(null)
  const uris = useRef(new Map()) // song id -> uri | null

  useEffect(() => {
    if (!enabled || !connected) return undefined
    let cancelled = false
    loadSdk().then((Spotify) => {
      if (cancelled) return
      const player = new Spotify.Player({ name: 'Wavely', getOAuthToken: (cb) => accessToken().then((t) => t && cb(t)), volume: 0.8 })
      player.addListener('ready', ({ device_id: id }) => { deviceRef.current = id; setDeviceId(id); setProblem(null) })
      player.addListener('not_ready', () => { deviceRef.current = null; setDeviceId(null) })
      player.addListener('player_state_changed', (s) => handlerRef.current?.(s))
      player.addListener('account_error', () => setProblem('Spotify Web Playback needs a Premium account.'))
      player.addListener('authentication_error', () => { forget(); setConnected(false); setProblem('Spotify sign-in expired. Connect again.') })
      player.addListener('initialization_error', () => setProblem("This browser can't play Spotify."))
      player.connect()
      playerRef.current = player
    }).catch((e) => setProblem(e.message))
    return () => {
      cancelled = true
      playerRef.current?.disconnect()
      playerRef.current = null
      deviceRef.current = null
      setDeviceId(null)
    }
  }, [enabled, connected])

  const resolve = useCallback(async (song) => {
    if (uris.current.has(song.id)) return uris.current.get(song.id)
    try {
      const track = await findTrack(song)
      uris.current.set(song.id, track?.uri || null)
      return track?.uri || null
    } catch {
      return null // not cached: a transient failure shouldn't hide the track from Spotify forever
    }
  }, [])

  const value = useMemo(() => ({
    enabled, connected, ready: Boolean(deviceId), problem,
    connect: beginLogin,
    disconnect: () => { forget(); setConnected(false); setDeviceId(null) },
    setConnected,
    resolve,
    onState: (fn) => { handlerRef.current = fn },
    play: async (uri, positionMs = 0) => {
      await playerRef.current?.activateElement?.() // browsers require a user gesture before audio can start
      return playOn(deviceRef.current, uri, positionMs)
    },
    getState: () => (playerRef.current?.getCurrentState() ?? Promise.resolve(null)),
    pause: () => playerRef.current?.pause(),
    resume: () => playerRef.current?.resume(),
    seek: (ms) => playerRef.current?.seek(ms),
    setVolume: (v) => playerRef.current?.setVolume(v),
  }), [enabled, connected, deviceId, problem, resolve])

  return <SpotifyContext.Provider value={value}>{children}</SpotifyContext.Provider>
}

export const useSpotify = () => useContext(SpotifyContext)
