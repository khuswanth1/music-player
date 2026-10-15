import { describe, expect, it } from 'vitest'
import { SECTIONS, applyLayoutPrefs, homeLayout } from '../lib/homeLayout'

describe('homeLayout', () => {
  it('always lists every section exactly once', () => {
    for (const signals of [{}, { recentCount: 8 }, { preferredLanguages: 2 }, { mixCount: 3, recentCount: 5 }]) {
      expect([...homeLayout(signals)].sort()).toEqual([...SECTIONS].sort())
    }
  })

  it('starts a heavy listener where they left off', () => {
    expect(homeLayout({ recentCount: 8, preferredLanguages: 1, mixCount: 4 }).slice(0, 2)).toEqual(['recent', 'mixes'])
  })

  it('starts someone with chosen languages or genres from their own mixes', () => {
    expect(homeLayout({ preferredLanguages: 2 })[0]).toBe('mixes')
    expect(homeLayout({ preferredGenres: 1 })[0]).toBe('mixes')
  })

  it('gives a new person who chose nothing the general shelves', () => {
    const order = homeLayout({})
    expect(order[0]).toBe('language_chips')
    expect(order.indexOf('recommended')).toBeLessThan(order.indexOf('genres'))
    expect(order.indexOf('language_chips')).toBeLessThan(order.indexOf('mixes')) // mixes only appear once there is something to build them from
  })

  it('treats different people differently', () => {
    expect(homeLayout({ recentCount: 9 })).not.toEqual(homeLayout({ preferredLanguages: 2 }))
    expect(homeLayout({ preferredLanguages: 2 })).not.toEqual(homeLayout({}))
  })

  it('lets a person reorder and hide shelves, ignoring unknown keys', () => {
    const auto = homeLayout({ preferredLanguages: 1 })
    const mine = applyLayoutPrefs(auto, { order: ['trending', 'nonsense', 'mixes'], hidden: ['genres', 'new'] })
    expect(mine.slice(0, 2)).toEqual(['trending', 'mixes'])
    expect(mine).not.toContain('genres')
    expect(mine).not.toContain('new')
    expect(mine).not.toContain('nonsense')
    expect(new Set(mine).size).toBe(mine.length)
    expect(applyLayoutPrefs(auto, {})).toEqual(auto)
  })
})
