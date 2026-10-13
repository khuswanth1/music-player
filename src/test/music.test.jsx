import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { ProviderStatusList } from '../components/ProviderStatus'
import TrackList from '../components/TrackList'
import { isUnavailable, licenseShort, songCover } from '../lib/tracks'

const player = { current: null, isPlaying: false, playList: vi.fn(), toggle: vi.fn(), addToQueue: vi.fn() }
vi.mock('../context/PlayerContext', () => ({ usePlayer: () => player }))
vi.mock('../context/LibraryContext', () => ({
  useLibrary: () => ({ isLiked: () => false, toggleLike: vi.fn(), playlists: [], addToPlaylist: vi.fn() }),
}))
vi.mock('../context/ToastContext', () => ({ useToast: () => ({ apiError: vi.fn(), success: vi.fn(), info: vi.fn() }) }))
vi.mock('../lib/languages', async (importOriginal) => ({
  ...(await importOriginal()),
  useLanguages: () => [{ code: 'te', name: 'Telugu', native_name: 'తెలుగు' }],
}))

const providerSong = (id, extra = {}) => ({
  id, title: `Track ${id}`, duration_ms: 200000, track_number: null, explicit: false, is_premium: false, is_published: true,
  has_audio: true, liked: false, artist: { id: 'ar', name: 'Artist' }, album: null, source: 'jamendo', source_name: 'Jamendo',
  source_url: `https://jamendo.test/${id}`, artwork_url: 'https://img.test/a.jpg', language: 'te', language_source: 'provider',
  availability: 'playable', playable: true, restriction_reason: null, download_allowed: true,
  license_code: 'cc-by-sa', license_name: 'CC BY-SA 3.0', license_url: 'https://creativecommons.org/licenses/by-sa/3.0/',
  attribution: `"Track ${id}" by Artist, licensed under CC BY-SA 3.0, via Jamendo.`, ...extra,
})

describe('track helpers', () => {
  it('labels licenses briefly', () => {
    expect(licenseShort({ license_code: 'cc-by-nc-sa' })).toBe('CC BY-NC-SA')
    expect(licenseShort({ license_code: 'cc0' })).toBe('CC0')
    expect(licenseShort({ license_code: 'platform' })).toBe('Stream only')
    expect(licenseShort({ license_code: 'unknown' })).toBe('Unverified')
    expect(licenseShort({ license_code: null })).toBeNull()
  })

  it('falls back to provider artwork and knows what is unplayable', () => {
    expect(songCover({ album: { cover_url: 'a.jpg' }, artwork_url: 'b.jpg' })).toBe('a.jpg')
    expect(songCover({ album: null, artwork_url: 'b.jpg' })).toBe('b.jpg')
    expect(isUnavailable({ playable: false })).toBe(true)
    expect(isUnavailable({ playable: true, is_published: true, has_audio: true })).toBe(false)
  })
})

describe('TrackList with provider tracks', () => {
  it('shows language, license and source, and blocks restricted tracks', async () => {
    const ok = providerSong('1')
    const blocked = providerSong('2', { playable: false, availability: 'restricted', download_allowed: false,
      restriction_reason: 'License could not be verified', license_code: 'unknown', license_name: 'License not stated' })
    render(<MemoryRouter><TrackList items={[ok, blocked].map((song) => ({ song }))} /></MemoryRouter>)

    expect(screen.getAllByTitle('Telugu')).toHaveLength(2)
    expect(screen.getByText('CC BY-SA')).toBeInTheDocument()
    expect(screen.getByText('Unverified')).toBeInTheDocument()
    expect(screen.getAllByText('License could not be verified').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Play Track 2' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'More options for Track 1' }))
    expect(screen.getByRole('menuitem', { name: /Download \(from Jamendo\)/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Open on Jamendo/ })).toHaveAttribute('href', 'https://jamendo.test/1')
    await userEvent.click(screen.getByRole('menuitem', { name: /Credits & license/ }))
    expect(screen.getByRole('dialog', { name: 'Credits & license' })).toHaveTextContent('"Track 1" by Artist, licensed under CC BY-SA 3.0, via Jamendo.')
    expect(screen.getByRole('link', { name: /CC BY-SA 3.0/ })).toHaveAttribute('href', 'https://creativecommons.org/licenses/by-sa/3.0/')
  })

  it('never offers a download the license or source does not allow', async () => {
    render(<MemoryRouter><TrackList items={[{ song: providerSong('3', { download_allowed: false }) }]} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'More options for Track 3' }))
    expect(screen.queryByRole('menuitem', { name: /Download/ })).toBeNull()
  })
})

describe('ProviderStatusList', () => {
  it('explains why a source returned nothing', () => {
    render(<ProviderStatusList providers={[
      { key: 'ia', name: 'Internet Archive', status: 'ok', count: 12 },
      { key: 'jamendo', name: 'Jamendo', status: 'not_configured', count: 0, message: 'Needs credentials' },
      { key: 'ov', name: 'Openverse', status: 'quota_exceeded', count: 0 },
    ]} />)
    expect(screen.getByText('Internet Archive').parentElement).toHaveTextContent('Internet Archive · 12')
    expect(screen.getByText('Jamendo').parentElement).toHaveTextContent('not configured')
    expect(screen.getByText('Openverse').parentElement).toHaveTextContent('daily limit reached')
  })
})
