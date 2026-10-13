"""MusicBrainz — open music metadata (https://musicbrainz.org/doc/MusicBrainz_API). Metadata only: no audio.

Used two ways:
* search results for recordings we have no authorized stream for, shown as "not available to stream";
* enrichment of imported tracks (language of the release, ISRC, release country) when the provider
  didn't supply them.

MusicBrainz allows one request per second per client and requires a descriptive User-Agent with contact
details (MUSIC_USER_AGENT). Core data is CC0.
"""

import re
import uuid
from dataclasses import dataclass

from app.core.config import get_settings
from app.music import languages as langs
from app.music.http import ProviderClient, ProviderError
from app.music.licensing import ProviderPolicy
from app.music.providers.base import Capability, MetadataRecording, MusicProvider

API = "https://musicbrainz.org/ws/2"
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def _escape(text: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", text)


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", text.casefold())


def _artist(credit: list[dict] | None) -> str:
    return "".join(f"{c.get('name', '')}{c.get('joinphrase', '')}" for c in credit or []) or "Unknown artist"


@dataclass
class Enrichment:
    recording_id: uuid.UUID
    isrc: str | None
    language: str | None
    country: str | None
    artist_id: uuid.UUID | None


class MusicBrainzProvider(MusicProvider):
    key = "musicbrainz"
    name = "MusicBrainz"
    homepage = "https://musicbrainz.org"
    terms_url = "https://musicbrainz.org/doc/About/Data_License"
    description = "The open music encyclopedia. Used for artist, release and recording metadata — never audio."
    attribution_html = 'Metadata from <a href="https://musicbrainz.org">MusicBrainz</a> (CC0).'
    capabilities = frozenset({Capability.search, Capability.metadata})
    policy = ProviderPolicy(stream=False, requires_open_license=True, download_links=False,
                            notes="Metadata only. Results without an authorized audio source are shown as unavailable.")

    def __init__(self) -> None:
        self.http = ProviderClient(self.key, rate_per_second=1, burst=1,
                                   daily_quota=get_settings().musicbrainz_daily_quota)

    def search_recordings(self, query: str, *, limit: int = 10) -> list[MetadataRecording]:
        body = self.http.get_json(f"{API}/recording", {"query": _escape(query), "fmt": "json", "limit": limit},
                                  max_wait=5)
        out = []
        for rec in body.get("recordings") or []:
            if (rec.get("score") or 0) < 70:
                continue
            release = (rec.get("releases") or [{}])[0]
            out.append(MetadataRecording(
                provider=self.key, id=rec["id"], title=rec.get("title") or "Untitled",
                artist_name=_artist(rec.get("artist-credit")), duration_ms=rec.get("length"),
                release_title=release.get("title"), release_date=release.get("date") or rec.get("first-release-date"),
                url=f"https://musicbrainz.org/recording/{rec['id']}", isrc=(rec.get("isrcs") or [None])[0]))
        return out

    def find_conflict(self, title: str, uploader: str, duration_ms: int | None) -> MetadataRecording | None:
        """An officially released recording with the same title and length by a *different* artist.

        Used for open-upload platforms: such a match means the upload is very likely someone else's
        commercial recording. Requires an exact (normalized) title and a length within 3 seconds, so
        common titles ("Friends", "Calm") by unrelated artists don't collide."""
        if not duration_ms:
            return None
        body = self.http.get_json(f"{API}/recording", {"query": f'recording:"{_escape(title)}"', "fmt": "json",
                                                       "limit": 10}, max_wait=5)
        want = _norm(title)
        uploader_key = _norm(uploader)
        for rec in body.get("recordings") or []:
            if (rec.get("score") or 0) < 90 or _norm(rec.get("title") or "") != want:
                continue
            if not rec.get("length") or abs(rec["length"] - duration_ms) > 3000:
                continue
            credited = _norm(_artist(rec.get("artist-credit")))
            if credited and (credited in uploader_key or uploader_key in credited):
                continue  # same artist: this may well be the rights holder
            official = [r for r in rec.get("releases") or [] if r.get("status") in (None, "Official")]
            if not official:
                continue
            return MetadataRecording(provider=self.key, id=rec["id"], title=rec.get("title") or title,
                                     artist_name=_artist(rec.get("artist-credit")), duration_ms=rec.get("length"),
                                     release_title=official[0].get("title"), release_date=official[0].get("date"),
                                     url=f"https://musicbrainz.org/recording/{rec['id']}")
        return None

    def enrich(self, title: str, artist: str, duration_ms: int | None) -> Enrichment | None:
        """Best confident match for one recording, or None. Never guesses below a high match score."""
        query = f'recording:"{_escape(title)}" AND artist:"{_escape(artist)}"'
        body = self.http.get_json(f"{API}/recording", {"query": query, "fmt": "json", "limit": 5}, max_wait=10)
        for rec in body.get("recordings") or []:
            if (rec.get("score") or 0) < 95:
                break
            if duration_ms and rec.get("length") and abs(rec["length"] - duration_ms) > 10_000:
                continue
            language = country = None
            release = next(iter(rec.get("releases") or []), None)
            if release:
                country = release.get("country") if len(release.get("country") or "") == 2 else None
                try:
                    detail = self.http.get_json(f"{API}/release/{release['id']}", {"fmt": "json"}, max_wait=10)
                    language = langs.normalize((detail.get("text-representation") or {}).get("language"))
                except ProviderError:
                    pass
            credit = (rec.get("artist-credit") or [{}])[0].get("artist") or {}
            return Enrichment(recording_id=uuid.UUID(rec["id"]), isrc=(rec.get("isrcs") or [None])[0],
                              language=language, country=country,
                              artist_id=uuid.UUID(credit["id"]) if credit.get("id") else None)
        return None
