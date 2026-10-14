import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AccessBadge } from '../components/TrackMeta'
import { accessOf, episodeToItem, isEpisode, licenseShort } from '../lib/tracks'

describe('availability labels', () => {
  it('derives full / preview / metadata from the song', () => {
    expect(accessOf({ access: 'preview' })).toBe('preview')
    expect(accessOf({ playable: true, has_audio: true, license_code: 'preview' })).toBe('preview')
    expect(accessOf({ playable: true, has_audio: true, license_code: 'cc-by' })).toBe('full')
    expect(accessOf({ playable: false, has_audio: true })).toBe('metadata')
    expect(licenseShort({ license_code: 'preview' })).toBe('Preview')
  })

  it('renders a badge per access kind, with an explanation', () => {
    const { rerender } = render(<AccessBadge song={{ access: 'full' }} />)
    expect(screen.getByText('Full track')).toBeInTheDocument()
    rerender(<AccessBadge song={{ access: 'preview' }} />)
    expect(screen.getByText('Preview')).toHaveAttribute('title', expect.stringMatching(/short clip/))
    rerender(<AccessBadge song={{ access: 'metadata' }} />)
    expect(screen.getByText('Metadata only')).toBeInTheDocument()
    rerender(<AccessBadge song={{ access: 'podcast' }} />)
    expect(screen.getByText('Podcast')).toBeInTheDocument()
  })
})

describe('podcast episodes in the player queue', () => {
  const episode = { id: 'itunes:42#abc', podcast_id: 'itunes:42', podcast_title: 'Talks', title: 'Ep 1', duration_s: 120, position_s: 45,
    audio_url: 'https://cdn.test/ep1.mp3', provider: 'itunes', image_url: 'https://img.test/c.jpg' }

  it('is shaped like a track and remembers where to resume', () => {
    const item = episodeToItem(episode)
    expect(isEpisode(item)).toBe(true)
    expect(item).toMatchObject({ id: 'itunes:42#abc', title: 'Ep 1', duration_ms: 120_000, resume_ms: 45_000, access: 'podcast' })
    expect(item.artist.name).toBe('Talks')
  })

  it('restarts a finished episode from the beginning', () => {
    expect(episodeToItem({ ...episode, completed: true }).resume_ms).toBe(0)
  })

  it('is not playable without an audio enclosure', () => {
    expect(episodeToItem({ ...episode, audio_url: null }).playable).toBe(false)
  })
})
