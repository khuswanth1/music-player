import { useSpotify } from '../context/SpotifyContext'
import { Button } from './ui'

/** Account-page card: connect your own Spotify Premium account to hear full versions of preview-only tracks. */
export default function SpotifyCard() {
  const s = useSpotify()
  return (
    <section className="rounded-lg bg-surface p-6 ring-1 ring-line" aria-labelledby="spotify-title">
      <h2 id="spotify-title" className="mb-2 text-xl font-bold">Spotify</h2>
      <p className="mb-4 text-sm text-muted">
        Connect your own Spotify Premium account and tracks that are only 30-second previews here play in full through Spotify&apos;s official
        player, on this device. Wavely never receives or stores Spotify audio.
      </p>
      {!s.enabled && (
        <p className="rounded-md bg-elevated p-3 text-sm text-muted">
          Not set up on this server. The site owner needs a free Spotify developer app and its Client ID in <code>VITE_SPOTIFY_CLIENT_ID</code>.
        </p>
      )}
      {s.enabled && !s.connected && <Button onClick={s.connect}>Connect Spotify</Button>}
      {s.enabled && s.connected && (
        <div className="flex flex-wrap items-center gap-3">
          <span className={`text-sm font-semibold ${s.ready ? 'text-accent' : 'text-muted'}`}>{s.ready ? 'Connected - full playback is on' : 'Connected - starting the player…'}</span>
          <Button variant="outline" onClick={s.disconnect}>Disconnect</Button>
        </div>
      )}
      {s.problem && <p role="alert" className="mt-3 text-sm text-amber-300">{s.problem}</p>}
    </section>
  )
}
