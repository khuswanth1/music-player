import { useState } from 'react'
import { ArrowDown, ArrowUp, Eye, EyeOff } from 'lucide-react'
import { meApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { applyLayoutPrefs, SECTIONS } from '../lib/homeLayout'
import { Button, Modal } from './ui'

export const SECTION_LABELS = {
  recent: 'Recently played', mixes: 'Your mixes', languages: 'Your languages', language_chips: 'Browse by language',
  for_you: 'Artists, albums & playlists for you', recommended: 'Made for you', featured: 'Featured releases',
  trending: 'Most played', new: 'New releases', world: 'Worldwide music', playlists: 'Community playlists', genres: 'Browse genres',
}

/** Lets a person reorder and hide the home shelves and pick the spacing. Saved to their account, so it follows them to any device. */
export default function CustomizeHome({ open, onClose, autoOrder }) {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const prefs = user?.ui_prefs || {}
  const [order, setOrder] = useState(() => applyLayoutPrefs(autoOrder, { order: prefs.home_order }))
  const [hidden, setHidden] = useState(prefs.home_hidden || [])
  const [density, setDensity] = useState(prefs.density || 'comfortable')
  const [saving, setSaving] = useState(false)

  const move = (i, d) => setOrder((o) => {
    const next = [...o]
    ;[next[i], next[i + d]] = [next[i + d], next[i]]
    return next
  })
  const toggle = (key) => setHidden((h) => (h.includes(key) ? h.filter((k) => k !== key) : [...h, key]))
  const reset = () => { setOrder(autoOrder); setHidden([]); setDensity('comfortable') }

  const save = async () => {
    const body = { home_order: order, home_hidden: hidden, density }
    setSaving(true)
    setUser((u) => ({ ...u, ui_prefs: body })) // applied at once; the server copy follows
    try {
      await meApi.saveSettings(body)
      onClose()
    } catch (err) {
      setUser((u) => ({ ...u, ui_prefs: prefs }))
      toast.apiError(err)
    } finally {
      setSaving(false)
    }
  }

  const rows = order.filter((k) => SECTIONS.includes(k))
  return (
    <Modal open={open} onClose={onClose} title="Customize your home">
      <p className="mb-3 text-sm text-muted">Reorder or hide shelves. This is saved to your account.</p>
      <ul className="max-h-[50vh] space-y-1 overflow-y-auto pr-1">
        {rows.map((key, i) => (
          <li key={key} className="flex items-center gap-2 rounded-md bg-elevated px-3 py-2">
            <span className={`flex-1 text-sm font-semibold ${hidden.includes(key) ? 'text-subtle line-through' : ''}`}>{SECTION_LABELS[key]}</span>
            <button type="button" aria-label={`Move ${SECTION_LABELS[key]} up`} disabled={i === 0} onClick={() => move(i, -1)} className="rounded p-1 hover:bg-hover disabled:opacity-30"><ArrowUp className="size-4" /></button>
            <button type="button" aria-label={`Move ${SECTION_LABELS[key]} down`} disabled={i === rows.length - 1} onClick={() => move(i, 1)} className="rounded p-1 hover:bg-hover disabled:opacity-30"><ArrowDown className="size-4" /></button>
            <button type="button" aria-label={`${hidden.includes(key) ? 'Show' : 'Hide'} ${SECTION_LABELS[key]}`} onClick={() => toggle(key)} className="rounded p-1 hover:bg-hover">
              {hidden.includes(key) ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center gap-2 text-sm">
        <span className="font-semibold">Spacing</span>
        {['comfortable', 'compact'].map((d) => (
          <button key={d} type="button" aria-pressed={density === d} onClick={() => setDensity(d)}
            className={`rounded-full px-3 py-1 capitalize ${density === d ? 'bg-white text-black' : 'bg-elevated hover:bg-hover'}`}>{d}</button>
        ))}
      </div>
      <div className="mt-5 flex justify-between">
        <Button variant="ghost" onClick={reset}>Reset</Button>
        <Button variant="primary" loading={saving} onClick={save}>Save</Button>
      </div>
    </Modal>
  )
}
