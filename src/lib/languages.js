import { useEffect, useState } from 'react'
import { musicApi } from '../api/endpoints'

// The language catalog rarely changes: load it once per page load and share it.
let cache = null
let inflight = null

export function loadLanguages() {
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = musicApi.languages()
      .then((list) => {
        cache = list
        return list
      })
      .finally(() => {
        inflight = null
      })
  }
  return inflight
}

/** All languages (with counts as of first load); [] until loaded. */
export function useLanguages() {
  const [list, setList] = useState(cache || [])
  useEffect(() => {
    if (cache) return undefined
    let alive = true
    loadLanguages().then((l) => alive && setList(l)).catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return list
}

export function languageName(list, code) {
  const lang = list.find((l) => l.code === code)
  return lang ? lang.name : code
}

export const LANGUAGE_SOURCES = {
  provider: 'reported by the source',
  musicbrainz: 'from MusicBrainz',
  script: 'detected from the writing system',
  tag: 'from the uploader’s tags',
  manual: 'set by an editor',
}

let providerCache = null

/** Provider display data (name, homepage, policy), loaded once. */
export function useProviders() {
  const [list, setList] = useState(providerCache || [])
  useEffect(() => {
    if (providerCache) return undefined
    let alive = true
    musicApi.providers().then((l) => {
      providerCache = l
      if (alive) setList(l)
    }).catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return list
}
