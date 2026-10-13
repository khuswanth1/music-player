import { Link } from 'react-router'
import { catalogApi } from '../api/endpoints'
import { AlbumCard, CardRow, PlaylistCard } from '../components/Cards'
import TrackList from '../components/TrackList'
import { CardGridSkeleton, Cover, ErrorState, SectionHeader, Skeleton, TrackListSkeleton } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { usePlayer } from '../context/PlayerContext'
import { useApi } from '../hooks/useApi'
import { greeting } from '../lib/format'
import { songCover } from '../lib/tracks'

export default function HomePage() {
  const { user } = useAuth()
  const { data, error, loading, reload } = useApi(() => catalogApi.home(), [])
  const { playList } = usePlayer()

  if (error) return <ErrorState error={error} onRetry={reload} />

  return (
    <div className="space-y-10 px-4 md:px-6">
      <section>
        <h1 className="mb-5 text-3xl font-extrabold tracking-tight">{greeting()}{user ? `, ${user.display_name.split(' ')[0]}` : ''}</h1>
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

      {(loading || data.recently_played.length > 0) && (
        <section>
          <SectionHeader title="Recently played" to="/history" LinkComponent={Link} />
          {loading ? <TrackListSkeleton rows={4} /> : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
              {data.recently_played.map((song, i) => (
                <button key={song.id} onClick={() => playList(data.recently_played, i, { type: 'history', name: 'Recently played' })}
                  className="group rounded-md bg-surface p-2 text-left hover:bg-elevated">
                  <Cover src={songCover(song)} seed={song.album?.id} alt="" className="w-full" />
                  <p className="mt-2 truncate text-sm font-semibold">{song.title}</p>
                  <p className="truncate text-xs text-muted">{song.artist.name}</p>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {!loading && data.languages.length > 0 && (
        <section>
          <SectionHeader title="Browse by language" to="/languages" linkLabel="All languages" LinkComponent={Link} />
          <div className="-mx-2 flex gap-2 overflow-x-auto px-2 pb-1 sm:flex-wrap">
            {data.languages.map((l) => (
              <Link key={l.code} to={`/language/${l.code}`}
                className="shrink-0 rounded-full bg-elevated px-4 py-2 text-sm font-semibold transition hover:bg-hover">
                <span lang={l.code}>{l.native_name}</span>
                <span className="ml-2 text-xs font-normal text-muted">{l.playable_count}</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {!loading && (data.in_your_languages.length > 0 ? (
        <section>
          <SectionHeader title="In your languages" to="/languages" linkLabel="Edit" LinkComponent={Link} />
          <TrackList items={data.in_your_languages.slice(0, 6).map((song) => ({ song }))} context={{ type: 'languages', name: 'In your languages' }} />
        </section>
      ) : !user?.preferred_languages?.length && (
        <section className="rounded-lg bg-gradient-to-r from-emerald-900/60 to-transparent p-5">
          <h2 className="text-xl font-bold">Hear more in your languages</h2>
          <p className="mt-1 text-sm text-muted">Pick the languages you listen to — Telugu, Hindi, Tamil, Korean, Spanish or any other — and we&apos;ll favour them.</p>
          <Link to="/languages" className="mt-4 inline-block rounded-full bg-white px-5 py-2 text-sm font-bold text-black hover:scale-105">Choose languages</Link>
        </section>
      ))}

      <section>
        <SectionHeader title="Made for you" />
        {loading ? <TrackListSkeleton rows={5} /> : data.recommended.length ? (
          <TrackList items={data.recommended.slice(0, 6).map((song) => ({ song }))} context={{ type: 'recommendations', name: 'Made for you' }} />
        ) : <p className="text-muted">Like a few songs and we&apos;ll tailor recommendations for you.</p>}
      </section>

      <section>
        <SectionHeader title="Featured releases" />
        {loading ? <CardGridSkeleton /> : <CardRow>{data.featured.map((a) => <AlbumCard key={a.id} album={a} />)}</CardRow>}
      </section>

      <section>
        <SectionHeader title="Trending this week" />
        {loading ? <TrackListSkeleton rows={5} /> : (
          <TrackList items={data.trending.slice(0, 5).map((song) => ({ song }))} context={{ type: 'trending', name: 'Trending' }} />
        )}
      </section>

      <section>
        <SectionHeader title="New releases" />
        {loading ? <CardGridSkeleton /> : <CardRow>{data.new_releases.map((a) => <AlbumCard key={a.id} album={a} />)}</CardRow>}
      </section>

      {!loading && data.public_playlists.length > 0 && (
        <section>
          <SectionHeader title="Playlists from the community" />
          <CardRow>{data.public_playlists.map((p) => <PlaylistCard key={p.id} playlist={p} />)}</CardRow>
        </section>
      )}

      {!loading && (
        <section>
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
      )}
    </div>
  )
}
