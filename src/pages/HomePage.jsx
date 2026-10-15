import { useState } from 'react'
import { Link } from 'react-router'
import { SlidersHorizontal } from 'lucide-react'
import { catalogApi, mixApi, musicApi } from '../api/endpoints'
import { AlbumCard, ArtistCard, CardRow, PlaylistCard } from '../components/Cards'
import CustomizeHome from '../components/CustomizeHome'
import HomeWorld from '../components/HomeSections'
import { MixCard } from '../components/MixCard'
import TrackList from '../components/TrackList'
import { CardGridSkeleton, Cover, ErrorState, SectionHeader, Skeleton, TrackListSkeleton } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { usePlayer } from '../context/PlayerContext'
import { useApi } from '../hooks/useApi'
import { greeting } from '../lib/format'
import { applyLayoutPrefs, homeLayout } from '../lib/homeLayout'
import { languageName, useLanguages } from '../lib/languages'
import { isUnavailable, songCover } from '../lib/tracks'

/** One shelf per language the person picked, so what they chose is the first thing the home screen plays. */
function LanguageShelf({ code }) {
  const languages = useLanguages()
  const { data, loading } = useApi((signal) => musicApi.languageTracks(code, { page_size: 6, sort: 'popular' }, signal), [code])
  const songs = (data?.items || []).filter((s) => !isUnavailable(s))
  if (!loading && songs.length === 0) return null
  const name = languageName(languages, code)
  return (
    <section>
      <SectionHeader title={`${name} for you`} to={`/language/${code}`} linkLabel={`More ${name}`} LinkComponent={Link} />
      {loading ? <TrackListSkeleton rows={4} /> : (
        <TrackList items={songs.map((song) => ({ song }))} context={{ type: 'language', id: code, name }} />
      )}
    </section>
  )
}

export default function HomePage() {
  const { user } = useAuth()
  const { data, error, loading, reload } = useApi(() => catalogApi.home(), [])
  const mixes = useApi(() => mixApi.list(), [user?.id, user?.preferred_languages?.join(','), user?.preferred_genres?.join(',')])
  const forYou = useApi(() => mixApi.forYou(), [user?.id, user?.preferred_languages?.join(','), user?.preferred_genres?.join(',')])
  const [customizing, setCustomizing] = useState(false)
  const { playList } = usePlayer()

  if (error) return <ErrorState error={error} onRetry={reload} />
  const preferred = user?.preferred_languages || []
  const recent = (data?.recently_played || []).filter((s) => !isUnavailable(s)) // tracks that are no longer offered stay out of the shelf
  const mixList = mixes.data || []

  // The order of the shelves is different for each person: see lib/homeLayout.js.
  const autoOrder = homeLayout({ recentCount: recent.length, preferredLanguages: preferred.length,
    preferredGenres: user?.preferred_genres?.length || 0, mixCount: mixList.length })
  const prefs = user?.ui_prefs || {}
  const order = applyLayoutPrefs(autoOrder, { order: prefs.home_order, hidden: prefs.home_hidden })
  const picks = forYou.data
  const gap = prefs.density === 'compact' ? 'space-y-6' : 'space-y-10'

  const sections = {
    mixes: mixList.length > 0 && (
      <section key="mixes">
        <SectionHeader title="Made just for you" />
        <CardRow>{mixList.map((m) => <MixCard key={m.id} mix={m} />)}</CardRow>
      </section>
    ),
    languages: preferred.slice(0, 3).map((code) => <LanguageShelf key={`lang-${code}`} code={code} />),
    recent: (loading || recent.length > 0) && (
      <section key="recent">
        <SectionHeader title="Recently played" to="/history" LinkComponent={Link} />
        {loading ? <TrackListSkeleton rows={4} /> : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
            {recent.map((song, i) => (
              <button key={song.id} onClick={() => playList(recent, i, { type: 'history', name: 'Recently played' })}
                className="group rounded-md bg-surface p-2 text-left hover:bg-elevated">
                <Cover src={songCover(song)} seed={song.album?.id} alt="" className="w-full" />
                <p className="mt-2 truncate text-sm font-semibold">{song.title}</p>
                <p className="truncate text-xs text-muted">{song.artist.name}</p>
              </button>
            ))}
          </div>
        )}
      </section>
    ),
    language_chips: !loading && data.languages.length > 0 && (
      <section key="language_chips">
        <SectionHeader title="Browse by language" to="/languages" linkLabel="All languages" LinkComponent={Link} />
        <div className="-mx-2 flex gap-2 overflow-x-auto px-2 pb-1 sm:flex-wrap">
          {[...data.languages].sort((a, b) => preferred.includes(b.code) - preferred.includes(a.code)).map((l) => (
            <Link key={l.code} to={`/language/${l.code}`}
              className="shrink-0 rounded-full bg-elevated px-4 py-2 text-sm font-semibold transition hover:bg-hover">
              <span lang={l.code}>{l.native_name}</span>
              <span className="ml-2 text-xs font-normal text-muted">{l.playable_count}</span>
            </Link>
          ))}
        </div>
      </section>
    ),
    for_you: picks && (picks.artists.length > 0 || picks.albums.length > 0 || picks.playlists.length > 0) && (
      <div key="for_you" className={gap}>
        {picks.artists.length > 0 && (
          <section>
            <SectionHeader title="Artists you may like" to="/artists" LinkComponent={Link} />
            <CardRow>{picks.artists.map((a) => <ArtistCard key={a.id} artist={a} />)}</CardRow>
          </section>
        )}
        {picks.albums.length > 0 && (
          <section>
            <SectionHeader title="Albums for you" />
            <CardRow>{picks.albums.map((a) => <AlbumCard key={a.id} album={a} />)}</CardRow>
          </section>
        )}
        {picks.playlists.length > 0 && (
          <section>
            <SectionHeader title="Playlists picked for you" />
            <CardRow>{picks.playlists.map((p) => <PlaylistCard key={p.id} playlist={p} />)}</CardRow>
          </section>
        )}
      </div>
    ),
    recommended: (
      <section key="recommended">
        <SectionHeader title="Made for you" />
        {loading ? <TrackListSkeleton rows={5} /> : data.recommended.length ? (
          <TrackList items={data.recommended.slice(0, 6).map((song) => ({ song }))} context={{ type: 'recommendations', name: 'Made for you' }} />
        ) : <p className="text-muted">Like a few songs and we&apos;ll tailor recommendations for you.</p>}
      </section>
    ),
    featured: (
      <section key="featured">
        <SectionHeader title="Featured releases" />
        {loading ? <CardGridSkeleton /> : <CardRow>{data.featured.map((a) => <AlbumCard key={a.id} album={a} />)}</CardRow>}
      </section>
    ),
    trending: (
      <section key="trending">
        <SectionHeader title="Worldwide music: most played here" />
        {loading ? <TrackListSkeleton rows={5} /> : (
          <TrackList items={data.trending.slice(0, 5).map((song) => ({ song }))} context={{ type: 'trending', name: 'Trending' }} />
        )}
      </section>
    ),
    new: (
      <section key="new">
        <SectionHeader title="New releases" />
        {loading ? <CardGridSkeleton /> : <CardRow>{data.new_releases.map((a) => <AlbumCard key={a.id} album={a} />)}</CardRow>}
      </section>
    ),
    world: !loading && <HomeWorld key="world" />,
    playlists: !loading && data.public_playlists.length > 0 && (
      <section key="playlists">
        <SectionHeader title="Playlists from the community" />
        <CardRow>{data.public_playlists.map((p) => <PlaylistCard key={p.id} playlist={p} />)}</CardRow>
      </section>
    ),
    genres: !loading && (
      <section key="genres">
        <SectionHeader title="Browse genres" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {data.genres.map((g) => (
            <Link key={g.id} to={`/genre/${g.slug}`} style={{ backgroundColor: g.color }}
              className="relative h-24 overflow-hidden rounded-lg p-3 text-lg font-extrabold text-black/85 transition hover:scale-[1.02]">
              {g.name}
            </Link>
          ))}
        </div>
      </section>
    ),
  }

  return (
    <div className={`${gap} px-4 md:px-6`}>
      <section>
        <div className="mb-5 flex items-center justify-between gap-3">
          <h1 className="text-3xl font-extrabold tracking-tight">{greeting()}{user ? `, ${user.display_name.split(' ')[0]}` : ''}</h1>
          {user && (
            <button type="button" onClick={() => setCustomizing(true)} aria-label="Customize home"
              className="flex items-center gap-2 rounded-full bg-elevated px-4 py-2 text-sm font-semibold hover:bg-hover">
              <SlidersHorizontal className="size-4" /> <span className="hidden sm:inline">Customize</span>
            </button>
          )}
        </div>
        {loading ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[...Array(8)].map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[...data.featured.slice(0, 4), ...data.new_releases.filter((a) => !a.is_featured).slice(0, 4)].map((album) => (
              <Link key={album.id} to={`/album/${album.id}`} className="group flex items-center gap-3 overflow-hidden rounded-md bg-white/5 pr-3 transition hover:bg-white/15">
                <Cover src={album.cover_url} seed={album.id} alt="" className="size-16 shrink-0" rounded="rounded-none" />
                <span className="truncate font-bold">{album.title}</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {!loading && !preferred.length && !data.in_your_languages.length && (
        <section className="rounded-lg bg-gradient-to-r from-emerald-900/60 to-transparent p-5">
          <h2 className="text-xl font-bold">Hear more in your languages</h2>
          <p className="mt-1 text-sm text-muted">Pick the languages you listen to — Telugu, Hindi, Tamil, Korean, Spanish or any other — and we&apos;ll favour them.</p>
          <Link to="/languages" className="mt-4 inline-block rounded-full bg-white px-5 py-2 text-sm font-bold text-black hover:scale-105">Choose languages</Link>
        </section>
      )}

      {order.map((key) => sections[key])}
      {customizing && <CustomizeHome open onClose={() => setCustomizing(false)} autoOrder={autoOrder} />}
    </div>
  )
}
