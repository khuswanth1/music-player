// Pure queue logic, kept separate from the <audio> element so it can be unit tested.

export const initialPlayerState = {
  queue: [], // songs in play order
  original: null, // un-shuffled order, restored when shuffle is turned off
  index: -1,
  queuedAhead: 0, // songs added via "Add to queue" that sit right after the current one
  context: null, // { type, id, name } of what is playing (album, playlist, …)
  shuffle: false,
  repeat: 'off', // off | all | one
  volume: 0.8,
  muted: false,
}

export function shuffled(list, rng = Math.random) {
  const a = [...list]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

export function playerReducer(state, action) {
  switch (action.type) {
    case 'load': {
      const { songs, startIndex = 0, context = null } = action
      if (!songs.length) return state
      if (state.shuffle) {
        const first = songs[startIndex]
        const rest = shuffled(songs.filter((_, i) => i !== startIndex), action.rng)
        return { ...state, queue: [first, ...rest], original: songs, index: 0, queuedAhead: 0, context }
      }
      return { ...state, queue: songs, original: null, index: startIndex, queuedAhead: 0, context }
    }
    case 'enqueue': {
      if (state.index < 0) return { ...state, queue: [action.song], index: 0, queuedAhead: 0 }
      const at = state.index + 1 + state.queuedAhead
      const queue = [...state.queue.slice(0, at), action.song, ...state.queue.slice(at)]
      const original = state.original ? [...state.original, action.song] : null
      return { ...state, queue, original, queuedAhead: state.queuedAhead + 1 }
    }
    case 'remove': {
      const i = action.index
      if (i === state.index || i < 0 || i >= state.queue.length) return state
      const queue = state.queue.filter((_, k) => k !== i)
      const ahead = i > state.index && i <= state.index + state.queuedAhead ? state.queuedAhead - 1 : state.queuedAhead
      return { ...state, queue, index: i < state.index ? state.index - 1 : state.index, queuedAhead: Math.max(0, ahead) }
    }
    case 'jump':
      if (action.index < 0 || action.index >= state.queue.length) return state
      return { ...state, index: action.index, queuedAhead: 0 }
    case 'next': {
      // `auto` = the track ended on its own (repeat-one replays it; a skip always advances).
      if (action.auto && state.repeat === 'one') return { ...state, restartToken: (state.restartToken || 0) + 1 }
      if (state.index + 1 < state.queue.length) {
        return { ...state, index: state.index + 1, queuedAhead: Math.max(0, state.queuedAhead - 1) }
      }
      if (state.repeat === 'all' && state.queue.length) return { ...state, index: 0, queuedAhead: 0 }
      return { ...state, ended: (state.ended || 0) + 1 }
    }
    case 'prev':
      return { ...state, index: Math.max(0, state.index - 1), queuedAhead: 0 }
    case 'toggleShuffle': {
      if (!state.queue.length) return { ...state, shuffle: !state.shuffle }
      const current = state.queue[state.index]
      if (!state.shuffle) {
        const rest = shuffled(state.queue.filter((_, i) => i !== state.index), action.rng)
        return { ...state, shuffle: true, original: state.queue, queue: [current, ...rest], index: 0, queuedAhead: 0 }
      }
      const base = state.original || state.queue
      const idx = Math.max(0, base.findIndex((s) => s.id === current?.id))
      return { ...state, shuffle: false, original: null, queue: base, index: idx, queuedAhead: 0 }
    }
    case 'cycleRepeat':
      return { ...state, repeat: { off: 'all', all: 'one', one: 'off' }[state.repeat] }
    case 'volume':
      return { ...state, volume: Math.min(1, Math.max(0, action.value)), muted: false }
    case 'toggleMute':
      return { ...state, muted: !state.muted }
    case 'restore':
      return { ...state, ...action.state }
    default:
      return state
  }
}
