// Spotify Web Playback integration (opt-in, per listener).
//
// A listener connects their OWN Spotify Premium account with the Authorization Code + PKCE flow, which needs no
// client secret, so nothing sensitive lives in this app. Full tracks are then played by Spotify's official Web
// Playback SDK under Spotify's terms; this app never touches or stores Spotify audio. Set VITE_SPOTIFY_CLIENT_ID
// (a free app from https://developer.spotify.com/dashboard) and add `<origin>/spotify/callback` as a redirect URI.

const AUTH = 'https://accounts.spotify.com/authorize'
const TOKEN = 'https://accounts.spotify.com/api/token'
const API = 'https://api.spotify.com/v1'
const STORE = 'wavely.spotify.v1'
const VERIFIER = 'wavely.spotify.pkce'
const SCOPES = 'streaming user-read-email user-read-private user-modify-playback-state user-read-playback-state'

export const clientId = () => import.meta.env?.VITE_SPOTIFY_CLIENT_ID || ''
export const redirectUri = () => `${window.location.origin}/spotify/callback`

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

export function randomString(length = 64) {
  const bytes = crypto.getRandomValues(new Uint8Array(length))
  return b64url(bytes).slice(0, length)
}

export async function challengeFor(verifier) {
  return b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)))
}

function read() {
  try {
    return JSON.parse(localStorage.getItem(STORE)) || null
  } catch {
    return null
  }
}

function write(tokens) {
  try {
    if (tokens) localStorage.setItem(STORE, JSON.stringify(tokens))
    else localStorage.removeItem(STORE)
  } catch {
    /* storage unavailable: the session just won't persist */
  }
}

export const isConnected = () => Boolean(read()?.refresh)
export const disconnect = () => write(null)

/** Send the browser to Spotify's consent screen. */
export async function beginLogin() {
  const verifier = randomString(96)
  const state = randomString(16)
  sessionStorage.setItem(VERIFIER, JSON.stringify({ verifier, state }))
  const params = new URLSearchParams({
    client_id: clientId(), response_type: 'code', redirect_uri: redirectUri(), scope: SCOPES,
    code_challenge_method: 'S256', code_challenge: await challengeFor(verifier), state,
  })
  window.location.assign(`${AUTH}?${params}`)
}

async function tokenRequest(body) {
  const res = await fetch(TOKEN, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams(body) })
  if (!res.ok) throw new Error(`Spotify sign-in failed (${res.status})`)
  const data = await res.json()
  const previous = read()
  const tokens = { access: data.access_token, refresh: data.refresh_token || previous?.refresh, expiresAt: Date.now() + data.expires_in * 1000 }
  write(tokens)
  return tokens
}

/** Finish the login on the callback page. Throws if the state doesn't match (CSRF) or the user declined. */
export async function completeLogin(search) {
  const params = new URLSearchParams(search)
  if (params.get('error')) throw new Error(params.get('error') === 'access_denied' ? 'You declined the Spotify connection.' : 'Spotify returned an error.')
  const saved = JSON.parse(sessionStorage.getItem(VERIFIER) || 'null')
  sessionStorage.removeItem(VERIFIER)
  if (!saved || saved.state !== params.get('state') || !params.get('code')) throw new Error('The Spotify sign-in could not be verified. Try again.')
  await tokenRequest({ grant_type: 'authorization_code', code: params.get('code'), redirect_uri: redirectUri(), client_id: clientId(), code_verifier: saved.verifier })
}

export async function accessToken() {
  let tokens = read()
  if (!tokens) return null
  if (tokens.expiresAt - Date.now() < 60_000) {
    try {
      tokens = await tokenRequest({ grant_type: 'refresh_token', refresh_token: tokens.refresh, client_id: clientId() })
    } catch {
      write(null) // the refresh token was revoked: treat as signed out
      return null
    }
  }
  return tokens.access
}

async function call(path, { method = 'GET', body, query } = {}) {
  const token = await accessToken()
  if (!token) throw Object.assign(new Error('Not connected to Spotify'), { status: 401 })
  const url = new URL(`${API}${path}`)
  Object.entries(query || {}).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined })
  if (!res.ok && res.status !== 204) throw Object.assign(new Error(`Spotify request failed (${res.status})`), { status: res.status })
  return res.status === 204 ? null : res.json().catch(() => null)
}

const norm = (s) => (s || '').toLowerCase().normalize('NFKD').replace(/\(.*?\)|\[.*?\]/g, ' ').replace(/[^\p{L}\p{N}]+/gu, ' ').trim()

/** Pick the Spotify track that is the same recording: title matches and the length is within 5 seconds. */
export function bestMatch(items, song) {
  const title = norm(song.title)
  const artist = norm(song.artist?.name)
  const scored = (items || []).map((t) => {
    const titleOk = norm(t.name) === title || norm(t.name).startsWith(title) || title.startsWith(norm(t.name))
    const artistOk = (t.artists || []).some((a) => artist && (norm(a.name).includes(artist) || artist.includes(norm(a.name))))
    const durationOk = !song.duration_ms || song.duration_ms < 45_000 || Math.abs(t.duration_ms - song.duration_ms) < 5000 || song.license_code === 'preview'
    return { t, ok: titleOk && artistOk && durationOk }
  })
  return scored.find((s) => s.ok)?.t || null
}

export async function findTrack(song) {
  const q = `track:${song.title.replace(/["()]/g, ' ')} artist:${(song.artist?.name || '').replace(/["()]/g, ' ')}`
  const res = await call('/search', { query: { q, type: 'track', limit: 5 } })
  return bestMatch(res?.tracks?.items, song)
}

export const playOn = (deviceId, uri, positionMs = 0) => call('/me/player/play', { method: 'PUT', query: { device_id: deviceId }, body: { uris: [uri], position_ms: positionMs } })

let sdkPromise = null
export function loadSdk() {
  if (window.Spotify) return Promise.resolve(window.Spotify)
  if (!sdkPromise) {
    sdkPromise = new Promise((resolve, reject) => {
      window.onSpotifyWebPlaybackSDKReady = () => resolve(window.Spotify)
      const script = document.createElement('script')
      script.src = 'https://sdk.scdn.co/spotify-player.js'
      script.onerror = () => { sdkPromise = null; reject(new Error('Could not load the Spotify player')) }
      document.head.appendChild(script)
    })
  }
  return sdkPromise
}
