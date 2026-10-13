import { useEffect, useRef } from 'react'

export const SHORTCUTS = [
  ['Space', 'Play / pause'],
  ['Shift + →', 'Next track'],
  ['Shift + ←', 'Previous track'],
  ['→ / ←', 'Seek forward / back 5 s'],
  ['↑ / ↓', 'Volume up / down'],
  ['M', 'Mute'],
  ['S', 'Shuffle'],
  ['R', 'Cycle repeat'],
  ['Q', 'Show queue'],
  ['/', 'Search'],
  ['?', 'Show shortcuts'],
]

function isTyping(target) {
  const tag = target?.tagName
  return target?.isContentEditable || tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

/** Global player shortcuts; ignored while typing in a form field. */
export function useKeyboardShortcuts(playerState, { onSearch, onToggleQueue, onHelp }) {
  // The player object changes on every position tick; read it through a ref so the listener binds once.
  const playerRef = useRef(playerState)
  playerRef.current = playerState
  useEffect(() => {
    const onKey = (e) => {
      const player = playerRef.current
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isTyping(e.target)) {
        if (e.key === 'Escape') e.target.blur()
        return
      }
      const handlers = {
        ' ': () => player.toggle(),
        ArrowRight: () => (e.shiftKey ? player.next() : player.seek(Math.min(player.duration, player.position + 5000))),
        ArrowLeft: () => (e.shiftKey ? player.prev() : player.seek(Math.max(0, player.position - 5000))),
        ArrowUp: () => player.setVolume(player.volume + 0.1),
        ArrowDown: () => player.setVolume(player.volume - 0.1),
        m: () => player.toggleMute(),
        s: () => player.toggleShuffle(),
        r: () => player.cycleRepeat(),
        q: () => onToggleQueue(),
        '/': () => onSearch(),
        '?': () => onHelp(),
      }
      const fn = handlers[e.key.length === 1 ? e.key.toLowerCase() : e.key] || (e.key === '?' && handlers['?'])
      if (!fn) return
      // Space on a focused button would also click it; let buttons keep their native behaviour.
      if (e.key === ' ' && e.target?.tagName === 'BUTTON') return
      e.preventDefault()
      fn()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onSearch, onToggleQueue, onHelp])
}
