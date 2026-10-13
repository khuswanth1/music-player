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
  if (song.license_code === 'platform') return 'Stream only'
  if (song.license_code === 'unknown') return 'Unverified'
  if (song.license_code === 'pdm') return 'Public domain'
  return song.license_code === 'cc0' ? 'CC0' : `CC ${song.license_code.slice(3).toUpperCase()}`
}
