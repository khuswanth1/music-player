// Every person gets their own home screen: the shelves are ordered by what that person actually does here.
//
//   - someone who listens a lot starts from where they left off (recently played, then their mixes)
//   - someone who has chosen languages or genres starts from those (their mixes and language shelves)
//   - a person can also reorder or hide shelves themselves (applyLayoutPrefs), which always wins
//   - someone with neither (new, or skipped onboarding) gets the general shelves: recommendations, featured, trending
//
// `signals` are cheap facts the page already has; the result is just an ordered list of section keys.
export const SECTIONS = ['recent', 'mixes', 'languages', 'language_chips', 'for_you', 'recommended', 'featured', 'trending', 'new', 'world', 'playlists', 'genres']

export function homeLayout({ recentCount = 0, preferredLanguages = 0, preferredGenres = 0, mixCount = 0 } = {}) {
  const personal = preferredLanguages > 0 || preferredGenres > 0 || mixCount > 0
  let head
  if (recentCount >= 4) head = ['recent', 'mixes', 'languages', 'language_chips', 'for_you']
  else if (personal) head = ['mixes', 'languages', 'for_you', 'language_chips', 'recent']
  else head = ['language_chips', 'recent']
  // Every section is always present exactly once; the general shelves follow whatever this person's head order was.
  return [...head, ...SECTIONS.filter((key) => !head.includes(key))]
}

/**
 * Apply the person's own choices on top of the automatic order: `order` is their saved order (unknown keys are
 * ignored, missing ones keep their automatic place after it) and `hidden` the sections they switched off.
 */
export function applyLayoutPrefs(auto, prefs = {}) {
  const hidden = new Set(prefs.hidden || [])
  const chosen = (prefs.order || []).filter((key) => SECTIONS.includes(key))
  const ordered = [...new Set([...chosen, ...auto])]
  return ordered.filter((key) => !hidden.has(key))
}
