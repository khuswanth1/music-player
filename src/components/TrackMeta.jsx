import { ExternalLink, Lock } from 'lucide-react'
import { LANGUAGE_SOURCES, languageName, useLanguages } from '../lib/languages'
import { isUnavailable, licenseShort } from '../lib/tracks'
import { Modal } from './ui'

export function LanguageTag({ code, className = '' }) {
  const languages = useLanguages()
  if (!code) return null
  const name = languageName(languages, code)
  return (
    <span title={name} className={`shrink-0 rounded-sm border border-zinc-600 px-1 text-[10px] font-bold uppercase leading-4 text-zinc-300 ${className}`}>
      {code === 'zxx' ? 'INST' : code}
    </span>
  )
}

export function LicenseBadge({ song, className = '' }) {
  const label = licenseShort(song)
  if (!label) return null
  const tone = song.license_code === 'unknown' ? 'text-amber-300 border-amber-400/40' : 'text-sky-300 border-sky-400/40'
  return <span title={song.license_name || label} className={`shrink-0 rounded-sm border px-1 text-[10px] font-bold leading-4 ${tone} ${className}`}>{label}</span>
}

export function RestrictionNote({ song, className = '' }) {
  if (!isUnavailable(song)) return null
  const reason = song.restriction_reason || (song.has_audio === false ? 'No audio available' : 'Not available')
  return (
    <span className={`flex min-w-0 items-center gap-1 text-xs text-amber-300/90 ${className}`} title={reason}>
      <Lock className="size-3 shrink-0" aria-hidden="true" /><span className="truncate">{reason}</span>
    </span>
  )
}

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

const AVAILABILITY = { playable: 'Playable here', restricted: 'Restricted', unavailable: 'No authorized audio' }

/** Attribution, license, source and availability for one track. */
export function CreditsModal({ song, open, onClose }) {
  const languages = useLanguages()
  if (!song) return null
  const external = song.source !== 'local'
  return (
    <Modal open={open} onClose={onClose} title="Credits & license">
      <div className="mb-3">
        <p className="text-lg font-bold">{song.title}</p>
        <p className="text-sm text-muted">{song.artist.name}{song.album ? ` · ${song.album.title}` : ''}</p>
      </div>
      <dl className="divide-y divide-line">
        <Row label="Source">
          {song.source_url
            ? <a href={song.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">{song.source_name} <ExternalLink className="size-3.5" /></a>
            : song.source_name}
        </Row>
        <Row label="License">
          {song.license_url
            ? <a href={song.license_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">{song.license_name} <ExternalLink className="size-3.5" /></a>
            : song.license_name || (external ? 'Not stated' : 'Hosted with the rights holder’s permission')}
        </Row>
        {song.attribution && <Row label="Attribution"><span className="text-zinc-200">{song.attribution}</span></Row>}
        <Row label="Language">
          {song.language ? `${languageName(languages, song.language)}${song.language_source ? ` (${LANGUAGE_SOURCES[song.language_source] || song.language_source})` : ''}` : 'Unknown'}
        </Row>
        <Row label="Availability">
          {AVAILABILITY[song.availability] || song.availability}
          {song.restriction_reason && <span className="block text-xs text-amber-300">{song.restriction_reason}</span>}
        </Row>
        {external && <Row label="Download">{song.download_allowed ? 'Allowed by the license and the source' : 'Not offered for this track'}</Row>}
      </dl>
      {external && (
        <p className="mt-4 text-xs text-subtle">
          Audio streams directly from {song.source_name}; nothing is copied to this service. Rights stay with the artist.
        </p>
      )}
    </Modal>
  )
}
