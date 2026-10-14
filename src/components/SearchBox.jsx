import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { Clock, Disc3, Globe2, Languages, Music2, Search, Tag, User2, X } from 'lucide-react'
import { searchApi } from '../api/endpoints'
import { useDebounce } from '../hooks/useApi'

const ICONS = { song: Music2, artist: User2, album: Disc3, language: Languages, genre: Tag, country: Globe2, recent: Clock }

/**
 * The global search field: debounced autocomplete from the catalog, your recent searches when focused and empty,
 * and live results on /search as you type. Suggestions never call the music providers (the results page does).
 */
export default function SearchBox() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const onSearch = location.pathname.startsWith('/search')
  const [q, setQ] = useState(params.get('q') || '')
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState([])
  const [active, setActive] = useState(-1)
  const boxRef = useRef(null)
  const debounced = useDebounce(q.trim(), 180)

  useEffect(() => {
    if (onSearch) setQ(params.get('q') || '')
  }, [onSearch, params])

  // Suggestions (or recent searches when the field is empty).
  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    const load = debounced
      ? searchApi.suggestions(debounced, controller.signal).then((r) => r.items)
      : searchApi.history().then((rows) => rows.map((r) => ({ text: r.query, type: 'recent', query: r.query })))
    load.then((list) => !controller.signal.aborted && (setItems(list), setActive(-1))).catch(() => !controller.signal.aborted && setItems([]))
    return () => controller.abort()
  }, [debounced, open])

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => !boxRef.current?.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const goSearch = (value) => {
    const text = value.trim()
    setOpen(false)
    if (!text) return navigate('/search')
    searchApi.record(text).catch(() => {})
    navigate(`/search?q=${encodeURIComponent(text)}`)
  }

  const choose = (item) => {
    setOpen(false)
    if (item.href) return navigate(item.href)
    setQ(item.query)
    goSearch(item.query)
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(items.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(-1, i - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (active >= 0 && items[active]) choose(items[active])
      else goSearch(q)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const update = (value) => {
    setQ(value)
    setOpen(true)
    navigate(value ? `/search?q=${encodeURIComponent(value)}` : '/search', { replace: onSearch })
  }

  const removeRecent = async (e, item) => {
    e.stopPropagation()
    await searchApi.clear(item.text).catch(() => {})
    setItems((list) => list.filter((x) => x !== item))
  }

  return (
    <div className="relative max-w-md flex-1" ref={boxRef} role="search">
      <Search className="pointer-events-none absolute left-3 top-1/2 size-5 -translate-y-1/2 text-muted" />
      <input id="global-search" type="search" value={q} onChange={(e) => update(e.target.value)} onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        role="combobox" aria-expanded={open && items.length > 0} aria-controls="search-suggestions" aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `suggestion-${active}` : undefined}
        placeholder="Songs, artists, podcasts, movies, “Telugu old songs”…" aria-label="Search songs, artists, albums, soundtracks, podcasts and playlists"
        className="w-full rounded-full border border-transparent bg-elevated py-2.5 pl-10 pr-4 text-sm placeholder:text-muted hover:border-line focus:border-white focus:outline-none" />
      {open && items.length > 0 && (
        <ul id="search-suggestions" role="listbox" className="absolute left-0 right-0 top-12 z-40 max-h-96 overflow-y-auto rounded-md bg-elevated p-1 shadow-2xl ring-1 ring-line">
          {!debounced && <li className="px-3 py-1.5 text-xs font-bold uppercase text-subtle" role="presentation">Recent searches</li>}
          {items.map((item, i) => {
            const Icon = ICONS[item.type] || Search
            return (
              <li key={`${item.type}-${item.text}-${i}`} id={`suggestion-${i}`} role="option" aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()} onClick={() => choose(item)} onMouseEnter={() => setActive(i)}
                className={`flex cursor-pointer items-center gap-3 rounded px-3 py-2 text-sm ${i === active ? 'bg-hover' : ''}`}>
                <Icon className="size-4 shrink-0 text-muted" />
                <span className="min-w-0 flex-1"><span className="block truncate">{item.text}</span>
                  {item.subtitle && <span className="block truncate text-xs text-muted">{item.subtitle}</span>}</span>
                {item.type === 'recent' && (
                  <button onMouseDown={(e) => e.preventDefault()} onClick={(e) => removeRecent(e, item)} aria-label={`Remove ${item.text} from recent searches`} className="text-muted hover:text-white"><X className="size-4" /></button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
