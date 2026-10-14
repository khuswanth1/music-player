import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { podcastApi, privateAlbumApi, worldApi } from '../api/endpoints'
import { PodcastCard } from '../pages/PodcastPages'
import { ArtistResultCard } from '../pages/ArtistsPage'
import { useLibrary } from '../context/LibraryContext'
import { useApi } from '../hooks/useApi'
import { languageName, useLanguages } from '../lib/languages'
import { plural } from '../lib/format'
import { CardRow, MediaCard, PlaylistCard } from './Cards'
import TrackList from './TrackList'
import { CardGridSkeleton, SectionHeader, TrackListSkeleton } from './ui'

/** Renders children only once scrolled near, so below-the-fold sections don't query the music providers up front. */
function Lazy({ children, minHeight = 160 }) {
  const ref = useRef(null)
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    if (seen || !ref.current) return undefined
    const io = new IntersectionObserver(([entry]) => entry.isIntersecting && (setSeen(true), io.disconnect()), { rootMargin: '300px' })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [seen])
  return <div ref={ref} style={seen ? undefined : { minHeight }}>{seen ? children : null}</div>
}

function Block({ title, to, linkLabel, note, load, empty = null, skeleton = 'cards', children }) {
  const { data, loading, error } = useApi(load, [])
  if (error || (!loading && (!data || (Array.isArray(data) ? data.length === 0 : false)))) return empty
  return (
    <section>
      <SectionHeader title={title} to={to} linkLabel={linkLabel} LinkComponent={Link} />
      {note && <p className="-mt-2 mb-3 text-xs text-subtle">{note}</p>}
      {loading ? (skeleton === 'tracks' ? <TrackListSkeleton rows={4} /> : <CardGridSkeleton count={6} />) : children(data)}
    </section>
  )
}

export function LatestMusic() {
  return (
    <Block title="Latest available music" to="/search?q=latest%20songs" note="Newest first by release date, from every enabled source." skeleton="tracks"
      load={() => worldApi.latest({ page_size: 6 })}>
      {(d) => <TrackList items={d.items.map((song) => ({ song }))} context={{ type: 'latest', name: 'Latest available music' }} />}
    </Block>
  )
}

export function OldAndClassic() {
  return (
    <Block title="Old and classic songs" to="/search?q=old%20songs" note="Released in or before 2005; ordered by listens here, then the source’s own popularity signal where it gives one."
      skeleton="tracks" load={() => worldApi.old({ page_size: 6 })}>
      {(d) => <TrackList items={d.items.map((song) => ({ song }))} context={{ type: 'old', name: 'Old and classic songs' }} />}
    </Block>
  )
}

export function BrowseCountries() {
  const { data } = useApi(() => worldApi.countries(), [])
  const known = (data || []).filter((c) => c.code)
  if (!known.length) return null
  return (
    <section>
      <SectionHeader title="Browse by country" to="/countries" LinkComponent={Link} />
      <p className="-mt-2 mb-3 text-xs text-subtle">Built from release countries the sources state; tracks without one are left out.</p>
      <div className="-mx-2 flex gap-2 overflow-x-auto px-2 pb-1 sm:flex-wrap">
        {known.map((c) => (
          <Link key={c.code} to={`/country/${c.code}`} className="shrink-0 rounded-full bg-elevated px-4 py-2 text-sm font-semibold hover:bg-hover">
            {c.name} <span className="ml-1 text-xs font-normal text-muted">{c.playable_count}</span>
          </Link>
        ))}
      </div>
    </section>
  )
}

export function MovieSoundtracks() {
  const languages = useLanguages()
  return (
    <Block title="Movie soundtracks" to="/movies" load={() => worldApi.soundtracks({ q: 'movie soundtrack', limit: 12 })}
      note="Albums from iTunes and MusicBrainz. Previews only unless a source supplies full audio.">
      {(d) => (
        <CardRow>
          {d.items.slice(0, 12).map((s) => (
            <MediaCard key={s.id} to={`/soundtrack/${encodeURIComponent(s.id)}`} image={s.artwork_url} seed={s.id} title={s.movie_title}
              subtitle={[s.release_year, s.language ? languageName(languages, s.language) : null, s.credited_artist].filter(Boolean).join(' · ')} />
          ))}
        </CardRow>
      )}
    </Block>
  )
}

export function PopularArtists() {
  return (
    <Block title="Artists in the catalog" to="/artists" note="Ranked by playable music and listens here — not a provider popularity chart." load={() => worldApi.catalogArtists({ limit: 12 })}>
      {(d) => <CardRow>{d.map((a) => <ArtistResultCard key={a.id} artist={a} />)}</CardRow>}
    </Block>
  )
}

export function HomePodcasts() {
  return (
    <Block title="Podcasts" to="/podcasts" note="Apple Podcasts search results for “podcast” — discovery, not a popularity ranking."
      load={() => podcastApi.search({ q: 'podcast', limit: 12 })}>
      {(d) => <CardRow>{d.podcasts.slice(0, 12).map((p) => <PodcastCard key={p.id} podcast={p} />)}</CardRow>}
    </Block>
  )
}

export function MyPlaylists() {
  const { playlists } = useLibrary()
  if (!playlists.length) return null
  return (
    <section>
      <SectionHeader title="Your playlists" to="/library" LinkComponent={Link} />
      <CardRow>{playlists.slice(0, 12).map((p) => <PlaylistCard key={p.id} playlist={p} />)}</CardRow>
    </section>
  )
}

export function MyPrivateAlbums() {
  return (
    <Block title="Your private albums" to="/private-albums" load={() => privateAlbumApi.list()}>
      {(d) => (
        <CardRow>
          {d.slice(0, 12).map((a) => (
            <MediaCard key={a.id} to={`/private-albums/${a.id}`} image={a.cover_url} seed={a.id} title={a.name} subtitle={`${plural(a.track_count, 'track')} · ${a.is_public ? 'Shared by link' : 'Private'}`} />
          ))}
        </CardRow>
      )}
    </Block>
  )
}

/** Everything below the fold on Home that comes from the worldwide providers, loaded as it scrolls into view. */
export default function HomeWorld() {
  return (
    <>
      <MyPlaylists />
      <Lazy><MyPrivateAlbums /></Lazy>
      <Lazy minHeight={260}><LatestMusic /></Lazy>
      <Lazy><BrowseCountries /></Lazy>
      <Lazy minHeight={260}><MovieSoundtracks /></Lazy>
      <Lazy><PopularArtists /></Lazy>
      <Lazy minHeight={260}><OldAndClassic /></Lazy>
      <Lazy><HomePodcasts /></Lazy>
    </>
  )
}
