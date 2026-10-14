/** Album art, else the provider's track artwork. */
export function songCover(song) {
  return song?.album?.cover_url || song?.artwork_url || null
}

export function isUnavailable(song) {
  return song.playable === false || song.is_published === false || song.has_audio === false
}

export function isExternal(song) {
  return Boolean(song?.source && song.source !== 'local')
}

/** Short license label for badges: "CC BY-SA", "CC0", "Stream only". */
export function licenseShort(song) {
  if (!song.license_code) return null
  if (song.license_code === 'preview') return 'Preview'
  if (song.license_code === 'platform') return 'Stream only'
  if (song.license_code === 'unknown') return 'Unverified'
  if (song.license_code === 'pdm') return 'Public domain'
  return song.license_code === 'cc0' ? 'CC0' : `CC ${song.license_code.slice(3).toUpperCase()}`
}

/** How much of the recording a track gives: full (complete), preview (provider's short clip) or metadata only. */
export const ACCESS = {
  full: { label: 'Full track', tone: 'text-emerald-300 border-emerald-400/40' },
  preview: { label: 'Preview', tone: 'text-amber-300 border-amber-400/40' },
  metadata: { label: 'Metadata only', tone: 'text-zinc-400 border-zinc-600' },
}

export function accessOf(song) {
  if (song?.access) return song.access
  if (isUnavailable(song || {})) return 'metadata'
  return song?.license_code === 'preview' ? 'preview' : 'full'
}

/** A podcast episode shaped like a queue item, so the player can treat it like a track. */
export function episodeToItem(ep) {
  return {
    kind: 'episode', id: ep.id, title: ep.title, duration_ms: (ep.duration_s || 0) * 1000, explicit: ep.explicit,
    artist: { id: null, name: ep.podcast_title || 'Podcast' }, album: null, artwork_url: ep.image_url,
    audio_url: ep.audio_url, podcast_id: ep.podcast_id, podcast_title: ep.podcast_title, image_url: ep.image_url,
    description: ep.description, published_at: ep.published_at, duration_s: ep.duration_s,
    resume_ms: (ep.completed ? 0 : ep.position_s || 0) * 1000, source: ep.provider, access: 'podcast', playable: Boolean(ep.audio_url),
  }
}

export const isEpisode = (item) => item?.kind === 'episode'
