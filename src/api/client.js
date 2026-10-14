// Fetch wrapper: JSON + FormData, typed errors, and transparent access-token refresh.
//
// The access token lives only in memory. The refresh token is an httpOnly cookie scoped to
// /api/v1/auth, so JavaScript can never read it; we call /auth/refresh to mint a new access token.

export const API_BASE = '/api/v1'

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let accessToken = null
let refreshInFlight = null
const listeners = new Set()

export function setAccessToken(token) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

/** Notified when the session can't be refreshed (user must sign in again). */
export function onSessionExpired(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

async function parseError(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON error body */
  }
  const err = body?.error
  return new ApiError(res.status, err?.code || 'http_error', err?.message || `Request failed (${res.status})`, err?.details)
}

/** One refresh at a time: concurrent 401s all wait on the same request. */
export function refreshSession() {
  if (!refreshInFlight) {
    // The refresh token lives only in an httpOnly cookie, so page scripts (and any XSS) can never read it.
    try { localStorage.removeItem('wavely_refresh') } catch { /* an older build kept it here */ }
    refreshInFlight = fetch(`${API_BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw await parseError(res)
        const data = await res.json()
        accessToken = data.access_token
        return data
      })
      .finally(() => {
        refreshInFlight = null
      })
  }
  return refreshInFlight
}

export async function api(path, { method = 'GET', body, query, signal, auth = true, retry = true } = {}) {
  let url = `${API_BASE}${path}`
  if (query) {
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') params.set(k, v)
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }
  const headers = {}
  let payload = body
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`

  const res = await fetch(url, { method, headers, body: payload, signal, credentials: 'include' })

  if (res.status === 401 && auth && retry && !path.startsWith('/auth/')) {
    try {
      await refreshSession()
    } catch {
      accessToken = null
      listeners.forEach((fn) => fn())
      throw await parseError(res)
    }
    return api(path, { method, body, query, signal, auth, retry: false })
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return null
  return res.json()
}
