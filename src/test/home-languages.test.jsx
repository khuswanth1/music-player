import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HomePage from '../pages/HomePage'

const api = vi.hoisted(() => ({ home: vi.fn(), languageTracks: vi.fn(), mixes: vi.fn(), forYou: vi.fn(), save: vi.fn() }))
vi.mock('../api/endpoints', () => ({
  catalogApi: { home: api.home },
  musicApi: { languageTracks: api.languageTracks },
  mixApi: { list: api.mixes, get: vi.fn(), forYou: api.forYou },
  meApi: { saveSettings: api.save },
  worldApi: {},
}))
const auth = vi.hoisted(() => ({ user: null }))
const setUser = vi.hoisted(() => vi.fn())
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: auth.user, setUser }) }))
vi.mock('../context/PlayerContext', () => ({
  usePlayer: () => ({ current: null, isPlaying: false, playList: vi.fn(), toggle: vi.fn(), addToQueue: vi.fn(), prefetch: vi.fn() }),
}))
vi.mock('../context/LibraryContext', () => ({
  useLibrary: () => ({ isLiked: () => false, toggleLike: vi.fn(), playlists: [], addToPlaylist: vi.fn() }),
}))
vi.mock('../context/ToastContext', () => ({ useToast: () => ({ apiError: vi.fn(), success: vi.fn(), info: vi.fn() }) }))
vi.mock('../components/HomeSections', () => ({ default: () => null }))
vi.mock('../lib/languages', async (importOriginal) => ({
  ...(await importOriginal()),
  useLanguages: () => [{ code: 'te', name: 'Telugu' }, { code: 'hi', name: 'Hindi' }],
}))

const song = (id, title) => ({ id, title, artist: { id: 'a', name: 'Artist' }, album: null, duration_ms: 200000, playable: true, has_audio: true, is_published: true })
const feed = (extra = {}) => ({
  featured: [], new_releases: [], trending: [], recommended: [], recently_played: [], genres: [], public_playlists: [],
  languages: [{ code: 'hi', native_name: 'Hindi-n', playable_count: 9 }, { code: 'te', native_name: 'Telugu-n', playable_count: 3 }],
  in_your_languages: [], ...extra,
})
const renderHome = () => render(<MemoryRouter><HomePage /></MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks()
  api.home.mockResolvedValue(feed())
  api.mixes.mockResolvedValue([])
  api.forYou.mockResolvedValue({ artists: [], albums: [], playlists: [] })
  api.save.mockResolvedValue({})
  api.languageTracks.mockImplementation(async (code) => ({ items: [song(`${code}1`, `${code} hit song`)] }))
})

describe('home screen and chosen languages', () => {
  it('puts a shelf for each chosen language at the top, ahead of everything else', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: ['te', 'hi'] }
    renderHome()
    expect(await screen.findByText('Telugu for you')).toBeInTheDocument()
    expect(screen.getByText('Hindi for you')).toBeInTheDocument()
    expect(await screen.findByText('te hit song')).toBeInTheDocument()
    expect(api.languageTracks).toHaveBeenCalledWith('te', expect.objectContaining({ page_size: 6 }), expect.anything())
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings.indexOf('Telugu for you')).toBeLessThan(headings.indexOf('Made for you'))
    expect(headings.indexOf('Telugu for you')).toBeLessThan(headings.indexOf('Hindi for you')) // in the order they were picked
  })

  it('shows general recommendations and the "choose languages" prompt when none were chosen', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: [] }
    renderHome()
    expect(await screen.findByText('Hear more in your languages')).toBeInTheDocument()
    expect(screen.getByText('Made for you')).toBeInTheDocument()
    expect(screen.queryByText(/for you$/, { selector: 'h2' }) && screen.queryByText('Telugu for you')).toBeNull()
    expect(api.languageTracks).not.toHaveBeenCalled()
  })

  it('lists the chosen languages first among the language chips', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: ['te'] }
    renderHome()
    await screen.findByText('Browse by language')
    const chips = screen.getAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/language/') && a.textContent.includes('-n'))
    expect(chips[0]).toHaveTextContent('Telugu-n')
  })
})

describe('personal mixes on home', () => {
  const mix = (id, title) => ({ id, kind: 'language', title, subtitle: 'Your daily picks', color: '#1e6b4f', song_count: 5, preview: [] })

  it('shows this person’s mixes first, before the general shelves', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: ['te'], preferred_genres: [] }
    api.mixes.mockResolvedValue([mix('language-te', 'Telugu Mix'), mix('discover', 'Discover Mix')])
    renderHome()
    expect(await screen.findByText('Telugu Mix')).toBeInTheDocument()
    expect(screen.getByText('Discover Mix')).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings.indexOf('Made just for you')).toBeLessThan(headings.indexOf('Made for you'))
  })

  it('shows no mixes row for someone without any', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: [] }
    renderHome()
    await screen.findByText('Made for you')
    expect(screen.queryByText('Made just for you')).toBeNull()
  })
})

describe('personal layout settings', () => {
  it('hides the shelves a person switched off and shows their for-you picks', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: [], ui_prefs: { home_hidden: ['genres', 'new'], home_order: ['trending'], density: 'compact' } }
    api.forYou.mockResolvedValue({ artists: [{ id: 'ar', name: 'Singer Z', image_url: null }], albums: [], playlists: [] })
    renderHome()
    expect(await screen.findByText('Artists you may like')).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).not.toContain('Browse genres')
    expect(headings).not.toContain('New releases')
    expect(headings.indexOf('Worldwide music: most played here')).toBeLessThan(headings.indexOf('Made for you')) // their own order wins
  })

  it('saves a new layout to the account and applies it straight away', async () => {
    auth.user = { id: 'u', display_name: 'Asha Rao', preferred_languages: [], ui_prefs: {} }
    renderHome()
    await userEvent.click(await screen.findByRole('button', { name: 'Customize home' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Hide Browse genres' }))
    await userEvent.click(screen.getByRole('button', { name: /compact/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ home_hidden: ['genres'], density: 'compact' })))
    expect(setUser).toHaveBeenCalled()
  })
})
