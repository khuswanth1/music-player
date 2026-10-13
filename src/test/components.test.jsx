import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import TrackList from '../components/TrackList'
import { livePosition } from '../context/SessionContext'
import { formatDuration, formatLongDuration, plural } from '../lib/format'

// TrackList depends on the player and library contexts; give it lightweight fakes.
const player = { current: null, isPlaying: false, playList: vi.fn(), toggle: vi.fn(), addToQueue: vi.fn() }
vi.mock('../context/PlayerContext', () => ({ usePlayer: () => player }))
vi.mock('../context/LibraryContext', () => ({
  useLibrary: () => ({ isLiked: (s) => Boolean(s.liked), toggleLike: vi.fn(), playlists: [], addToPlaylist: vi.fn() }),
}))

const song = (id, extra = {}) => ({
  id, title: `Track ${id}`, duration_ms: 125000, track_number: 1, explicit: false, is_premium: false, is_published: true,
  has_audio: true, liked: false, artist: { id: 'ar', name: 'Artist' }, album: { id: 'al', title: 'Album', cover_url: null }, ...extra,
})

describe('format helpers', () => {
  it('formats durations', () => {
    expect(formatDuration(125000)).toBe('2:05')
    expect(formatDuration(3_725_000)).toBe('1:02:05')
    expect(formatDuration(NaN)).toBe('0:00')
    expect(formatLongDuration(90 * 60000)).toBe('1 hr 30 min')
    expect(plural(1, 'song')).toBe('1 song')
    expect(plural(3, 'song')).toBe('3 songs')
  })
})

describe('livePosition', () => {
  it('adds elapsed time while playing, correcting for clock skew', () => {
    const now = Date.now()
    const state = { position_ms: 1000, is_playing: true, current_song: { duration_ms: 60000 },
      // server clock is 5 s behind ours; the state changed 2 s ago by the server's clock
      server_time: new Date(now - 5000).toISOString(), state_updated_at: new Date(now - 7000).toISOString() }
    expect(livePosition(state, now)).toBeGreaterThanOrEqual(2900)
    expect(livePosition(state, now)).toBeLessThan(3200)
    expect(livePosition({ ...state, is_playing: false }, now)).toBe(1000)
  })
})

describe('TrackList', () => {
  it('renders rows and plays the clicked track with its context', async () => {
    const songs = [song('1'), song('2', { is_premium: true, explicit: true })]
    render(<MemoryRouter><TrackList items={songs.map((s) => ({ song: s }))} context={{ type: 'album', id: 'al' }} /></MemoryRouter>)
    expect(screen.getByText('Track 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Premium')).toBeInTheDocument()
    expect(screen.getAllByText('2:05')).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'Play Track 2' }))
    expect(player.playList).toHaveBeenCalledWith(songs, 1, { type: 'album', id: 'al' })
  })

  it('offers move up/down only where it makes sense when reordering is allowed', async () => {
    const onReorder = vi.fn()
    const songs = [song('1'), song('2')]
    render(<MemoryRouter><TrackList items={songs.map((s) => ({ song: s }))} onReorder={onReorder} /></MemoryRouter>)
    await userEvent.click(screen.getByRole('button', { name: 'More options for Track 1' }))
    expect(screen.queryByRole('menuitem', { name: /Move up/ })).toBeNull()
    await userEvent.click(screen.getByRole('menuitem', { name: /Move down/ }))
    expect(onReorder).toHaveBeenCalledWith(0, 1)
  })
})
