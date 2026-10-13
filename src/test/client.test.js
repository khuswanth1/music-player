import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, getAccessToken, onSessionExpired, setAccessToken } from '../api/client'

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.restoreAllMocks()
  setAccessToken(null)
})

describe('api client', () => {
  it('sends the bearer token and parses JSON', async () => {
    setAccessToken('tok-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, { ok: true }))
    await expect(api('/me')).resolves.toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/me')
    expect(init.headers.Authorization).toBe('Bearer tok-1')
    expect(init.credentials).toBe('include')
  })

  it('builds query strings and skips empty values', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(200, {}))
    await api('/search', { query: { q: 'neon', type: undefined, genre: '', page: 2 } })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/search?q=neon&page=2')
  })

  it('turns error envelopes into ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(402, { error: { code: 'premium_required', message: 'Needs Premium' } }))
    const err = await api('/x').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 402, code: 'premium_required', message: 'Needs Premium' })
  })

  it('refreshes once for concurrent 401s, then retries each request', async () => {
    setAccessToken('expired')
    let refreshCalls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      if (url.endsWith('/auth/refresh')) {
        refreshCalls += 1
        await new Promise((r) => setTimeout(r, 10))
        return json(200, { access_token: 'fresh', user: {} })
      }
      return init.headers.Authorization === 'Bearer fresh' ? json(200, { url }) : json(401, { error: { code: 'token_expired' } })
    })
    const results = await Promise.all([api('/a'), api('/b'), api('/c')])
    expect(results.map((r) => r.url)).toEqual(['/api/v1/a', '/api/v1/b', '/api/v1/c'])
    expect(refreshCalls).toBe(1) // single-flight
    expect(getAccessToken()).toBe('fresh')
  })

  it('notifies listeners when the session cannot be refreshed', async () => {
    setAccessToken('expired')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) =>
      url.endsWith('/auth/refresh') ? json(401, { error: { code: 'refresh_invalid' } }) : json(401, { error: { code: 'token_expired' } }))
    const expired = vi.fn()
    const off = onSessionExpired(expired)
    await expect(api('/me')).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledOnce()
    expect(getAccessToken()).toBeNull()
    off()
  })

  it('sends FormData without forcing a JSON content type', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(201, {}))
    const fd = new FormData()
    fd.append('file', new Blob(['x']), 'a.png')
    await api('/me/avatar', { method: 'POST', body: fd })
    const init = fetchMock.mock.calls[0][1]
    expect(init.body).toBe(fd)
    expect(init.headers['Content-Type']).toBeUndefined()
  })
})
