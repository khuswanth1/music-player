import { api } from './client'

const form = (fields) => {
  const fd = new FormData()
  for (const [k, v] of Object.entries(fields)) {
    if (v !== undefined && v !== null && v !== '') fd.append(k, v)
  }
  return fd
}

export const authApi = {
  providers: () => api('/auth/providers', { auth: false }),
  login: (email, password) => api('/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  loginCode: (email) => api('/auth/login-code', { method: 'POST', body: { email }, auth: false }),
  verifyLoginCode: (email, code) => api('/auth/login-code/verify', { method: 'POST', body: { email, code }, auth: false }),
  register: (data) => api('/auth/register', { method: 'POST', body: data, auth: false }),
  logout: () => api('/auth/logout', { method: 'POST', auth: false }),
  forgot: (email) => api('/auth/forgot-password', { method: 'POST', body: { email }, auth: false }),
  reset: (token, new_password) => api('/auth/reset-password', { method: 'POST', body: { token, new_password }, auth: false }),
}

export const meApi = {
  get: () => api('/me'),
  update: (data) => api('/me', { method: 'PATCH', body: data }),
  changePassword: (data) => api('/me/password', { method: 'POST', body: data }),
  avatar: (file) => api('/me/avatar', { method: 'POST', body: form({ file }) }),
  remove: () => api('/me', { method: 'DELETE' }),
}

export const catalogApi = {
  home: () => api('/browse/home'),
  newReleases: (page = 1) => api('/browse/new-releases', { query: { page } }),
  genres: () => api('/genres'),
  genre: (slug) => api(`/genres/${slug}`),
  songs: (query) => api('/songs', { query }),
  song: (id) => api(`/songs/${id}`),
  streamUrl: (id, fast = false) => api(`/songs/${id}/stream-url`, fast ? { query: { fast: true } } : {}),
  artists: (query) => api('/artists', { query }),
  artist: (id) => api(`/artists/${id}`),
  artistTopSongs: (id) => api(`/artists/${id}/top-songs`),
  artistAlbums: (id) => api(`/artists/${id}/albums`),
  albums: (query) => api('/albums', { query }),
  album: (id) => api(`/albums/${id}`),
  search: (query, signal) => api('/search', { query, signal }),
}

export const musicApi = {
  languages: (query) => api('/languages', { query }),
  language: (code) => api(`/languages/${code}`),
  languageTracks: (code, query, signal) => api(`/languages/${code}/tracks`, { query, signal }),
  fetchLanguage: (code) => api(`/languages/${code}/fetch`, { method: 'POST' }),
  myLanguages: () => api('/me/languages'),
  setMyLanguages: (languages) => api('/me/languages', { method: 'PUT', body: { languages } }),
  providers: () => api('/providers'),
  globalSearch: (query, signal) => api('/search/global', { query, signal }),
  charts: () => api('/charts'),
  chart: (id) => api(`/charts/${encodeURIComponent(id)}`),
  download: (id) => api(`/songs/${id}/download`),
}

export const libraryApi = {
  liked: (page = 1, page_size = 50) => api('/me/liked-songs', { query: { page, page_size } }),
  like: (id) => api(`/me/liked-songs/${id}`, { method: 'PUT' }),
  unlike: (id) => api(`/me/liked-songs/${id}`, { method: 'DELETE' }),
  following: () => api('/me/following'),
  follow: (id) => api(`/me/following/${id}`, { method: 'PUT' }),
  unfollow: (id) => api(`/me/following/${id}`, { method: 'DELETE' }),
  albums: () => api('/me/albums'),
  saveAlbum: (id) => api(`/me/albums/${id}`, { method: 'PUT' }),
  unsaveAlbum: (id) => api(`/me/albums/${id}`, { method: 'DELETE' }),
  savedPlaylists: () => api('/me/saved-playlists'),
  savePlaylist: (id) => api(`/me/saved-playlists/${id}`, { method: 'PUT' }),
  unsavePlaylist: (id) => api(`/me/saved-playlists/${id}`, { method: 'DELETE' }),
  history: (page = 1) => api('/me/history', { query: { page, page_size: 50 } }),
  clearHistory: () => api('/me/history', { method: 'DELETE' }),
  recordPlay: (data) => api('/me/history', { method: 'POST', body: data }),
  recentlyPlayed: () => api('/me/recently-played'),
  recommendations: () => api('/me/recommendations'),
  player: () => api('/me/player'),
  savePlayer: (data) => api('/me/player', { method: 'PUT', body: data }),
}

export const playlistApi = {
  mine: () => api('/me/playlists'),
  get: (id) => api(`/playlists/${id}`),
  create: (data) => api('/playlists', { method: 'POST', body: data }),
  update: (id, data) => api(`/playlists/${id}`, { method: 'PATCH', body: data }),
  remove: (id) => api(`/playlists/${id}`, { method: 'DELETE' }),
  cover: (id, file) => api(`/playlists/${id}/cover`, { method: 'POST', body: form({ file }) }),
  addTracks: (id, song_ids, position) => api(`/playlists/${id}/tracks`, { method: 'POST', body: { song_ids, position } }),
  removeTrack: (id, itemId) => api(`/playlists/${id}/tracks/${itemId}`, { method: 'DELETE' }),
  reorder: (id, from_index, to_index) => api(`/playlists/${id}/tracks/reorder`, { method: 'PATCH', body: { from_index, to_index } }),
  regenerateInvite: (id) => api(`/playlists/${id}/invite`, { method: 'POST' }),
  join: (id, code) => api(`/playlists/${id}/join`, { method: 'POST', body: { code } }),
  removeCollaborator: (id, userId) => api(`/playlists/${id}/collaborators/${userId}`, { method: 'DELETE' }),
  userPlaylists: (userId) => api(`/users/${userId}/playlists`),
}

export const billingApi = {
  plans: () => api('/billing/plans'),
  status: () => api('/billing/subscription'),
  checkout: (plan) => api('/billing/checkout', { method: 'POST', body: { plan } }),
  portal: () => api('/billing/portal', { method: 'POST' }),
  cancel: () => api('/billing/cancel', { method: 'POST' }),
  resume: () => api('/billing/resume', { method: 'POST' }),
  payments: () => api('/billing/payments'),
  devComplete: (session) => api('/billing/dev/complete', { method: 'POST', body: { session } }),
  verifyRazorpay: (data) => api('/billing/razorpay/verify', { method: 'POST', body: data }),
}

export const sessionApi = {
  create: (name) => api('/sessions', { method: 'POST', body: { name } }),
  active: () => api('/sessions/active'),
  get: (id) => api(`/sessions/${id}`),
  join: (invite_code) => api('/sessions/join', { method: 'POST', body: { invite_code } }),
  control: (id, body) => api(`/sessions/${id}/control`, { method: 'POST', body }),
  leave: (id) => api(`/sessions/${id}/leave`, { method: 'POST' }),
  end: (id) => api(`/sessions/${id}`, { method: 'DELETE' }),
}

export const adminApi = {
  stats: () => api('/admin/stats'),
  analytics: (days) => api('/admin/analytics', { query: { days } }),
  users: (query) => api('/admin/users', { query }),
  updateUser: (id, data) => api(`/admin/users/${id}`, { method: 'PATCH', body: data }),
  deleteUser: (id) => api(`/admin/users/${id}`, { method: 'DELETE' }),
  grantPremium: (id, days) => api(`/admin/users/${id}/grant-premium`, { method: 'POST', body: { days } }),
  playlists: (query) => api('/admin/playlists', { query }),
  subscriptions: (query) => api('/admin/subscriptions', { query }),
  revokeSubscription: (id) => api(`/admin/subscriptions/${id}/revoke`, { method: 'POST' }),
  payments: (query) => api('/admin/payments', { query }),
  webhooks: (query) => api('/admin/webhooks', { query }),
  webhook: (id) => api(`/admin/webhooks/${id}`),
  retryWebhook: (id) => api(`/admin/webhooks/${id}/retry`, { method: 'POST' }),
  // catalog writes
  createGenre: (data) => api('/genres', { method: 'POST', body: data }),
  updateGenre: (id, data) => api(`/genres/${id}`, { method: 'PATCH', body: data }),
  deleteGenre: (id) => api(`/genres/${id}`, { method: 'DELETE' }),
  createArtist: (data) => api('/artists', { method: 'POST', body: data }),
  updateArtist: (id, data) => api(`/artists/${id}`, { method: 'PATCH', body: data }),
  artistImage: (id, file) => api(`/artists/${id}/image`, { method: 'POST', body: form({ file }) }),
  deleteArtist: (id) => api(`/artists/${id}`, { method: 'DELETE' }),
  createAlbum: (data) => api('/albums', { method: 'POST', body: data }),
  updateAlbum: (id, data) => api(`/albums/${id}`, { method: 'PATCH', body: data }),
  albumCover: (id, file) => api(`/albums/${id}/cover`, { method: 'POST', body: form({ file }) }),
  deleteAlbum: (id) => api(`/albums/${id}`, { method: 'DELETE' }),
  createSong: (fields) => api('/songs', { method: 'POST', body: form(fields) }),
  updateSong: (id, data) => api(`/songs/${id}`, { method: 'PATCH', body: data }),
  replaceAudio: (id, file) => api(`/songs/${id}/audio`, { method: 'PUT', body: form({ file }) }),
  deleteSong: (id) => api(`/songs/${id}`, { method: 'DELETE' }),
  // open catalogs
  providers: () => api('/admin/providers'),
  syncLanguage: (language, pages = 1) => api('/admin/catalog/sync', { method: 'POST', body: { language, pages } }),
  verifySong: (id) => api(`/admin/songs/${id}/verify`, { method: 'POST' }),
  takedown: (id, reason) => api(`/admin/songs/${id}/takedown`, { method: 'POST', body: reason ? { reason } : {} }),
  restore: (id) => api(`/admin/songs/${id}/takedown`, { method: 'DELETE' }),
}

export const searchApi = {
  global: (query, signal) => api('/search/global', { query, signal }),
  suggestions: (q, signal) => api('/search/suggestions', { query: { q }, signal }),
  history: () => api('/me/search-history'),
  record: (query) => api('/me/search-history', { method: 'POST', body: { query } }),
  clear: (query) => api('/me/search-history', { method: 'DELETE', query: { query } }),
}

export const worldApi = {
  latest: (query, signal) => api('/music/latest', { query, signal }),
  old: (query, signal) => api('/music/old', { query, signal }),
  countries: () => api('/music/countries'),
  genres: (query) => api('/music/genres', { query }),
  tracks: (query, signal) => api('/music/tracks', { query, signal }),
  albums: (query, signal) => api('/music/albums', { query, signal }),
  fetchGenre: (genre, page = 0) => api('/music/genres/fetch', { method: 'POST', body: { genre, page } }),
  soundtracks: (query, signal) => api('/music/soundtracks', { query, signal }),
  movies: (query, signal) => api('/music/movies', { query, signal }),
  soundtrack: (id) => api(`/music/soundtracks/${encodeURIComponent(id)}`),
  searchArtists: (query, signal) => api('/artists/search', { query, signal }),
  catalogArtists: (query, signal) => api('/music/artists', { query, signal }),
  artistProfile: (id) => api(`/artists/${id}/profile`),
  searchAlbums: (query, signal) => api('/albums/search', { query, signal }),
}

export const podcastApi = {
  categories: () => api('/podcasts/categories'),
  search: (query, signal) => api('/podcasts/search', { query, signal }),
  searchEpisodes: (query, signal) => api('/podcasts/episodes/search', { query, signal }),
  get: (id) => api(`/podcasts/${encodeURIComponent(id)}`),
  episodes: (id, query, signal) => api(`/podcasts/${encodeURIComponent(id)}/episodes`, { query, signal }),
  following: () => api('/me/podcasts'),
  follow: (podcast) => api(`/me/podcasts/${encodeURIComponent(podcast.id)}`, {
    method: 'PUT', body: { title: podcast.title, publisher: podcast.publisher, image_url: podcast.image_url, language: podcast.language } }),
  unfollow: (id) => api(`/me/podcasts/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  latestFollowed: () => api('/me/podcasts/latest/episodes'),
  saved: () => api('/me/episodes'),
  save: (ep) => api('/me/episodes/save', { method: 'PUT', query: { episode_id: ep.id }, body: episodeSnapshot(ep) }),
  unsave: (ep) => api('/me/episodes/save', { method: 'DELETE', query: { episode_id: ep.id } }),
  progress: (ep, position_s, completed = false) => api('/me/episodes/progress', {
    method: 'PUT', body: { ...episodeSnapshot(ep), episode_id: ep.id, position_s: Math.round(position_s), completed } }),
  history: (page = 1) => api('/me/episodes/progress', { query: { page, page_size: 30 } }),
}

function episodeSnapshot(ep) {
  return { podcast_id: ep.podcast_id, title: ep.title, podcast_title: ep.podcast_title, image_url: ep.image_url,
    audio_url: ep.audio_url, duration_s: ep.duration_s, published_at: ep.published_at,
    description: ep.description ? ep.description.slice(0, 4000) : null }
}

export const privateAlbumApi = {
  list: (query) => api('/private-albums', { query }),
  get: (id) => api(`/private-albums/${id}`),
  shared: (code) => api(`/private-albums/shared/${encodeURIComponent(code)}`),
  create: (data) => api('/private-albums', { method: 'POST', body: data }),
  update: (id, data) => api(`/private-albums/${id}`, { method: 'PATCH', body: data }),
  cover: (id, file) => api(`/private-albums/${id}/cover`, { method: 'POST', body: form({ file }) }),
  share: (id) => api(`/private-albums/${id}/share`, { method: 'POST' }),
  remove: (id) => api(`/private-albums/${id}`, { method: 'DELETE' }),
  addTracks: (id, song_ids) => api(`/private-albums/${id}/tracks`, { method: 'POST', body: { song_ids } }),
  removeTrack: (id, itemId) => api(`/private-albums/${id}/tracks/${itemId}`, { method: 'DELETE' }),
}
