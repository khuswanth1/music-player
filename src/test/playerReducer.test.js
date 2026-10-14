import { describe, expect, it } from 'vitest'
import { initialPlayerState, playerReducer, shuffled } from '../context/playerReducer'

const song = (id) => ({ id, title: `Song ${id}`, duration_ms: 1000 })
const songs = ['a', 'b', 'c', 'd'].map(song)
const ids = (state) => state.queue.map((s) => s.id)
const current = (state) => state.queue[state.index]?.id

// deterministic "random" for shuffle tests
const seq = (...values) => { let i = 0; return () => values[i++ % values.length] }

describe('playerReducer', () => {
  it('loads a list and starts at the chosen track', () => {
    const s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 2, context: { type: 'album', id: 'x' } })
    expect(ids(s)).toEqual(['a', 'b', 'c', 'd'])
    expect(current(s)).toBe('c')
    expect(s.context).toEqual({ type: 'album', id: 'x' })
  })

  it('advances, then stops at the end when repeat is off', () => {
    let s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 3 })
    s = playerReducer(s, { type: 'next' })
    expect(current(s)).toBe('d')
    expect(s.ended).toBe(1)
  })

  it('wraps around with repeat all and replays with repeat one', () => {
    let s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 3 })
    s = playerReducer(s, { type: 'cycleRepeat' }) // all
    s = playerReducer(s, { type: 'next' })
    expect(current(s)).toBe('a')
    s = playerReducer(s, { type: 'cycleRepeat' }) // one
    const replay = playerReducer(s, { type: 'next', auto: true })
    expect(current(replay)).toBe('a')
    expect(replay.restartToken).toBe(1)
    // a manual skip still advances under repeat-one
    expect(current(playerReducer(s, { type: 'next' }))).toBe('b')
  })

  it('navigates to previous track and wraps around when repeat all is active', () => {
    let s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 2 })
    s = playerReducer(s, { type: 'prev' })
    expect(current(s)).toBe('b')
    s = playerReducer(s, { type: 'prev' })
    expect(current(s)).toBe('a')
    // at index 0 with repeat off, stays at 0
    s = playerReducer(s, { type: 'prev' })
    expect(current(s)).toBe('a')
    // with repeat all, wraps around to the last track
    s = playerReducer(s, { type: 'cycleRepeat' }) // all
    s = playerReducer(s, { type: 'prev' })
    expect(current(s)).toBe('d')
  })

  it('"Add to queue" keeps added songs in the order they were added, right after the current one', () => {
    let s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 0 })
    s = playerReducer(s, { type: 'enqueue', song: song('x') })
    s = playerReducer(s, { type: 'enqueue', song: song('y') })
    expect(ids(s)).toEqual(['a', 'x', 'y', 'b', 'c', 'd'])
    s = playerReducer(s, { type: 'next' })
    expect(current(s)).toBe('x')
    expect(s.queuedAhead).toBe(1)
  })

  it('enqueue into an empty player makes that song current', () => {
    const s = playerReducer(initialPlayerState, { type: 'enqueue', song: song('x') })
    expect(current(s)).toBe('x')
  })

  it('removes upcoming songs but never the current one', () => {
    let s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 1 })
    s = playerReducer(s, { type: 'remove', index: 0 })
    expect(ids(s)).toEqual(['b', 'c', 'd'])
    expect(current(s)).toBe('b')
    expect(playerReducer(s, { type: 'remove', index: s.index })).toBe(s)
  })

  it('shuffle keeps the current song first and restores the original order when turned off', () => {
    let s = playerReducer(initialPlayerState, { type: 'load', songs, startIndex: 1 })
    s = playerReducer(s, { type: 'toggleShuffle', rng: seq(0, 0.5, 0.9) })
    expect(current(s)).toBe('b')
    expect(s.index).toBe(0)
    expect([...ids(s)].sort()).toEqual(['a', 'b', 'c', 'd'])
    s = playerReducer(s, { type: 'next' })
    const playing = current(s)
    s = playerReducer(s, { type: 'toggleShuffle' })
    expect(ids(s)).toEqual(['a', 'b', 'c', 'd'])
    expect(current(s)).toBe(playing)
  })

  it('clamps volume and unmutes on change', () => {
    let s = playerReducer(initialPlayerState, { type: 'toggleMute' })
    s = playerReducer(s, { type: 'volume', value: 1.7 })
    expect(s.volume).toBe(1)
    expect(s.muted).toBe(false)
    expect(playerReducer(s, { type: 'volume', value: -1 }).volume).toBe(0)
  })

  it('shuffled() is a permutation', () => {
    const out = shuffled([1, 2, 3, 4, 5])
    expect(out.sort()).toEqual([1, 2, 3, 4, 5])
  })
})

describe('restoring a saved queue', () => {
  const song = (id, extra = {}) => ({ id, title: id, playable: true, has_audio: true, is_published: true, ...extra })

  it('drops tracks that can no longer be played and keeps the current one in place', () => {
    const queue = [song('a', { playable: false }), song('b'), song('c', { has_audio: false }), song('d')]
    const state = playerReducer(initialPlayerState, { type: 'restore', state: { queue, index: 3 } })
    expect(state.queue.map((s) => s.id)).toEqual(['b', 'd'])
    expect(state.queue[state.index].id).toBe('d')
  })

  it('starts at the first playable track when the saved current one is gone, and empties if nothing is playable', () => {
    const q = [song('a', { playable: false }), song('b')]
    expect(playerReducer(initialPlayerState, { type: 'restore', state: { queue: q, index: 0 } }).queue[0].id).toBe('b')
    const none = playerReducer(initialPlayerState, { type: 'restore', state: { queue: [song('x', { playable: false })], index: 0 } })
    expect(none.queue).toEqual([])
    expect(none.index).toBe(-1)
  })
})
