import { describe, expect, it } from 'vitest'
import { bestMatch, challengeFor, completeLogin, randomString } from '../lib/spotify'

describe('spotify helpers', () => {
  it('derives the PKCE challenge exactly as RFC 7636 specifies', async () => {
    expect(await challengeFor('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk')).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
    expect(randomString(96)).toMatch(/^[A-Za-z0-9_-]{96}$/)
  })

  const song = { title: 'Golden', artist: { name: 'HUNTR/X' }, duration_ms: 194_000, license_code: 'preview' }
  it('matches the same recording by title and artist, and rejects look-alikes', () => {
    const items = [
      { uri: 'spotify:track:a', name: 'Golden (Instrumental)', artists: [{ name: 'Somebody Else' }], duration_ms: 190_000 },
      { uri: 'spotify:track:b', name: 'Golden', artists: [{ name: 'HUNTR/X' }, { name: 'EJAE' }], duration_ms: 194_500 },
    ]
    expect(bestMatch(items, song).uri).toBe('spotify:track:b')
    expect(bestMatch([items[0]], song)).toBeNull()
    expect(bestMatch([], song)).toBeNull()
  })

  it('refuses a callback whose state does not match (CSRF) or that was declined', async () => {
    sessionStorage.setItem('wavely.spotify.pkce', JSON.stringify({ verifier: 'v', state: 'expected' }))
    await expect(completeLogin('?code=abc&state=forged')).rejects.toThrow(/could not be verified/)
    await expect(completeLogin('?error=access_denied')).rejects.toThrow(/declined/)
  })
})
