import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SearchBox from '../components/SearchBox'
import TrackList from '../components/TrackList'
import { EpisodeRow } from '../pages/PodcastPages'

const api = vi.hoisted(() => ({
  suggestions: vi.fn(), history: vi.fn(), record: vi.fn(), clear: vi.fn(), addTracks: vi.fn(), albums: vi.fn(),
}))
vi.mock('../api/endpoints', () => ({
  searchApi: { suggestions: api.suggestions, history: api.history, record: api.record, clear: api.clear },
  podcastApi: { save: vi.fn(), unsave: vi.fn() },
  musicApi: { download: vi.fn() },
  privateAlbumApi: { list: api.albums, addTracks: api.addTracks },
}))
const player = { current: null, isPlaying: false, playList: vi.fn(), toggle: vi.fn(), addToQueue: vi.fn() }
vi.mock('../context/PlayerContext', () => ({ usePlayer: () => player }))
vi.mock('../context/LibraryContext', () => ({
  useLibrary: () => ({ isLiked: () => false, toggleLike: vi.fn(), playlists: [], addToPlaylist: vi.fn() }),
}))
const toast = { apiError: vi.fn(), success: vi.fn(), info: vi.fn() }
vi.mock('../context/ToastContext', () => ({ useToast: () => toast }))
vi.mock('../lib/languages', async (importOriginal) => ({ ...(await importOriginal()), useLanguages: () => [] }))

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}
const renderBox = () => render(
  <MemoryRouter initialEntries={['/']}>
    <SearchBox />
    <Routes><Route path="*" element={<Where />} /></Routes>
  </MemoryRouter>,
)

beforeEach(() => {
  vi.clearAllMocks()
  api.record.mockResolvedValue({})
  api.clear.mockResolvedValue({})
})

describe('global search box', () => {
  it('shows recent searches when focused and empty, and re-runs one on click', async () => {
    api.history.mockResolvedValue([{ query: 'telugu old songs', last_searched_at: 'now' }])
    renderBox()
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByRole('option', { name: /telugu old songs/ }))
    expect(screen.getByTestId('where')).toHaveTextContent('/search?q=telugu%20old%20songs')
    expect(api.record).toHaveBeenCalledWith('telugu old songs')
  })

  it('autocompletes with the keyboard and opens an artist suggestion directly', async () => {
    api.suggestions.mockResolvedValue({ items: [
      { text: 'Arijit Singh', type: 'artist', subtitle: 'Artist', href: '/artist/abc' },
      { text: 'Telugu songs', type: 'language', href: '/language/te' },
    ] })
    renderBox()
    await userEvent.type(screen.getByRole('combobox'), 'ari')
    expect(await screen.findByRole('option', { name: /Arijit Singh/ })).toBeInTheDocument()
    await userEvent.keyboard('{ArrowDown}{Enter}')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/artist/abc'))
  })
})

describe('podcast episodes', () => {
  const episode = { id: 'itunes:1#a', podcast_id: 'itunes:1', podcast_title: 'Talks', title: 'Ep 1', duration_s: 600, position_s: 300,
    audio_url: 'https://cdn.test/a.mp3', playable: true, published_at: '2026-10-01T00:00:00Z' }

  it('offers Resume and hands the player a queue item that remembers the position', async () => {
    render(<MemoryRouter><EpisodeRow episode={episode} queue={[episode]} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'Play Ep 1' }))
    expect(screen.getByRole('button', { name: 'Play Ep 1' })).toHaveTextContent('Resume')
    const [items, index] = player.playList.mock.calls[0]
    expect(index).toBe(0)
    expect(items[0]).toMatchObject({ kind: 'episode', audio_url: 'https://cdn.test/a.mp3', resume_ms: 300_000 })
  })

  it('cannot be played without publisher audio', () => {
    render(<MemoryRouter><EpisodeRow episode={{ ...episode, audio_url: null, playable: false }} /></MemoryRouter>)
    expect(screen.getByRole('button', { name: 'Play Ep 1' })).toBeDisabled()
    expect(screen.getByText('No playable audio')).toBeInTheDocument()
  })
})

describe('track menu: more ways to hear a track', () => {
  const song = { id: 's1', title: 'Clip', duration_ms: 30000, explicit: false, is_premium: false, is_published: true, has_audio: true,
    playable: true, access: 'preview', artist: { id: 'a', name: 'Artist' }, album: null, source: 'itunes', source_name: 'iTunes', license_code: 'preview' }

  it('previews link out to Spotify, full tracks do not', async () => {
    const { unmount } = render(<MemoryRouter><TrackList items={[{ song }]} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'More options for Clip' }))
    expect(screen.getByRole('menuitem', { name: /Find the full song on Spotify/ })).toHaveAttribute('href', expect.stringContaining('open.spotify.com/search/Clip%20Artist'))
    unmount()
    render(<MemoryRouter><TrackList items={[{ song: { ...song, access: 'full', license_code: 'cc-by' } }]} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'More options for Clip' }))
    expect(screen.queryByRole('menuitem', { name: /Spotify/ })).not.toBeInTheDocument()
  })

  it('adds a track to a private album from the menu', async () => {
    api.albums.mockResolvedValue([{ id: 'al1', name: 'Road trip' }])
    api.addTracks.mockResolvedValue({})
    render(<MemoryRouter><TrackList items={[{ song }]} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'More options for Clip' }))
    await userEvent.click(screen.getByRole('menuitem', { name: /Add to private album/ }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Road trip' }))
    expect(api.addTracks).toHaveBeenCalledWith('al1', ['s1'])
    expect(toast.success).toHaveBeenCalledWith('Added to Road trip')
  })
})
