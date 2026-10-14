"""Apple iTunes Search & Lookup API for track metadata and 30-second audio previews."""

from datetime import date

from app.core.config import get_settings
from app.music import languages as langs
from app.music.genres import canonical_genre
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import License, ProviderPolicy
from app.music.providers.base import Capability, MusicProvider, ProviderTrack

API = "https://itunes.apple.com"

ITUNES_FULL_LICENSE = License(
    code="full",
    name="Full track stream (resolved audio)",
)



# The iTunes storefront whose catalog best covers each language. A storefront is a market, not a language:
# it only widens what the search can find; each track's language is still derived per track (below).
LANGUAGE_STORES = {
    "te": "IN", "hi": "IN", "ta": "IN", "kn": "IN", "ml": "IN", "bn": "IN", "mr": "IN", "pa": "IN", "gu": "IN",
    "ko": "KR", "ja": "JP", "zh": "TW", "es": "ES", "fr": "FR", "de": "DE", "pt": "BR", "ar": "SA", "it": "IT",
    "ru": "RU", "tr": "TR", "id": "ID", "th": "TH", "vi": "VN", "en": "US",
}
# Genre names that are language names ("Telugu", "Tamil") identify the language; "Bollywood" is Hindi-language
# film music by definition. Broader genres (K-Pop, Soundtrack, Regional Indian...) say nothing reliable.
_GENRE_LANGUAGE = {"bollywood": "hi"}


def track_language(genre: str | None) -> str | None:
    if not genre:
        return None
    key = genre.strip().casefold()
    return _GENRE_LANGUAGE.get(key) or (langs.normalize(genre) if key in {n.name.casefold() for n in langs.BY_CODE.values()} else None)


class ITunesProvider(MusicProvider):
    key = "itunes"
    name = "iTunes"
    homepage = "https://www.apple.com/itunes/"
    terms_url = "https://www.apple.com/legal/internet-services/itunes/"
    description = "Apple iTunes catalog previews (30-second audio preview clips provided by Apple)."
    attribution_html = 'Audio previews provided courtesy of <a href="https://www.apple.com/itunes/">iTunes</a>.'
    capabilities = frozenset({Capability.search, Capability.playback, Capability.language, Capability.genre})
    policy = ProviderPolicy(
        stream=True,
        requires_open_license=False,
        download_links=False,
        notes="30-second promotional audio preview clips supplied by Apple iTunes Search API.",
    )
    open_uploads = False

    def __init__(self) -> None:
        self.http = ProviderClient(self.key, rate_per_second=5, burst=5, daily_quota=get_settings().itunes_daily_quota)

    def is_configured(self) -> bool:
        return True

    def _to_track(self, r: dict) -> ProviderTrack | None:
        track_id = str(r.get("trackId") or "")
        if not track_id:
            return None
        title = r.get("trackName") or r.get("trackCensoredName") or "Untitled"
        artist = r.get("artistName") or "Unknown artist"
        preview_url = r.get("previewUrl")
        artwork = r.get("artworkUrl100") or r.get("artworkUrl60")
        if artwork and isinstance(artwork, str):
            artwork = artwork.replace("100x100bb.jpg", "600x600bb.jpg")

        release_date = None
        if r.get("releaseDate"):
            try:
                release_date = date.fromisoformat(str(r["releaseDate"])[:10])
            except ValueError:
                pass

        attribution = f'"{title}" by {artist}. All rights reserved; 30-second preview provided by iTunes.'
        return ProviderTrack(
            provider=self.key,
            provider_track_id=track_id,
            title=title,
            artist_name=artist,
            provider_artist_id=str(r.get("artistId")) if r.get("artistId") else None,
            artist_url=r.get("artistViewUrl"),
            album_title=r.get("collectionName"),
            provider_album_id=str(r.get("collectionId")) if r.get("collectionId") else None,
            album_url=r.get("collectionViewUrl"),
            release_date=release_date,
            duration_ms=r.get("trackTimeMillis") or 210000,
            artwork_url=artwork,
            tags=[r.get("primaryGenreName")] if r.get("primaryGenreName") else [],
            stream_url=preview_url,
            source_url=r.get("trackViewUrl"),
            license=ITUNES_FULL_LICENSE,

            attribution=attribution,
            explicit=r.get("trackExplicitness") == "explicit",
            language=track_language(r.get("primaryGenreName")),
            language_source="provider",
        )


    def search(self, query: str, *, language: str | None = None, limit: int = 20, offset: int = 0) -> list[ProviderTrack]:
        params = {
            "term": query, "media": "music", "entity": "song", "limit": min(limit, 50), "offset": offset,
            "country": LANGUAGE_STORES.get(language or ""),
        }
        body = self.http.get_json(f"{API}/search", params=params, cache=True)
        results = body.get("results") if isinstance(body, dict) else []
        if not results and params["country"]:  # some storefronts answer with nothing; the default one usually doesn't
            body = self.http.get_json(f"{API}/search", params={**params, "country": None}, cache=True)
            results = body.get("results") if isinstance(body, dict) else []
        tracks = []
        for r in results:
            t = self._to_track(r)
            if t:
                tracks.append(t)
        return tracks

    def browse(self, *, language: str | None = None, genre: str | None = None, limit: int = 20,
               offset: int = 0) -> list[ProviderTrack]:
        """Songs for a language page. iTunes has no popularity feed, so this is plain search relevance, and only
        tracks whose language can be established (language-named genre, or the language's own script) are kept."""
        if not get_settings().music_previews_visible:
            # Everything iTunes streams is a 30-second clip; with previews hidden, browsing would only fill the catalog
            # with tracks nobody can play. (Search still runs: it finds artists and albums.)
            raise ProviderError(self.key, "unsupported", "iTunes only provides 30-second previews, which are hidden")
        if language and language not in langs.BY_CODE:
            raise ProviderError(self.key, "bad_response", "Unknown language")
        if not language and not genre:
            raise ProviderError(self.key, "bad_response", "Browsing needs a language or a genre")
        term = " ".join(x for x in (langs.BY_CODE[language].name if language else None, genre or "songs") if x)
        found = self.search(term, language=language, limit=limit, offset=offset)
        kept = []
        for t in found:
            if language:
                t.language = t.language or langs.detect_from_script(t.title, t.album_title, t.artist_name)
                if t.language != language:
                    continue
            if genre and canonical_genre(t.tags) != genre:
                continue  # iTunes matched the word elsewhere (title, artist); keep only tracks it files under this genre
            kept.append(t)
        return kept

    # --- albums and artists (metadata for the soundtrack, album and artist pages) --------------------------

    def search_albums(self, term: str, *, country: str | None = None, limit: int = 25, offset: int = 0) -> list[dict]:
        params = {"term": term, "media": "music", "entity": "album", "limit": min(limit, 50), "offset": offset,
                  "country": country}
        body = self.http.get_json(f"{API}/search", params=params)
        return [r for r in body.get("results", []) if r.get("collectionId")]

    def lookup_album(self, collection_id: str) -> tuple[dict | None, list[ProviderTrack]]:
        body = self.http.get_json(f"{API}/lookup", {"id": collection_id, "entity": "song", "limit": 200})
        results = body.get("results", [])
        album = next((r for r in results if r.get("wrapperType") == "collection"), None)
        tracks = [t for r in results if r.get("wrapperType") == "track" and (t := self._to_track(r))]
        return album, tracks

    def search_artists(self, term: str, *, country: str | None = None, limit: int = 15) -> list[dict]:
        body = self.http.get_json(f"{API}/search", {"term": term, "media": "music", "entity": "musicArtist",
                                                    "limit": min(limit, 50), "country": country})
        return [r for r in body.get("results", []) if r.get("artistId")]

    def lookup_artist(self, artist_id: str, *, entity: str, limit: int = 50) -> list[dict]:
        """`entity` is `album` or `song`; the first result is the artist itself."""
        body = self.http.get_json(f"{API}/lookup", {"id": artist_id, "entity": entity, "limit": limit,
                                                    "sort": "recent" if entity == "album" else None})
        return body.get("results", [])

    def fetch_track(self, provider_track_id: str) -> ProviderTrack | None:
        try:
            body = self.http.get_json(f"{API}/lookup", {"id": provider_track_id}, cache=False)
            results = body.get("results") if isinstance(body, dict) else []
            for r in results:
                if str(r.get("trackId")) == str(provider_track_id):
                    return self._to_track(r)
        except ProviderError:
            return None
        return None

    def playback_url(self, provider_track_id: str, stored_url: str) -> str:
        return stored_url
